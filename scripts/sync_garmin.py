#!/usr/bin/env python3
"""
Fetches Garmin Connect data and writes data.json for the triathlon dashboard.
Runs on a schedule via GitHub Actions.
"""
import os
import json
import base64
import datetime
import time
import sys

try:
    import garth
    from garminconnect import Garmin
except ImportError:
    sys.exit("Run: pip install garminconnect garth")


def login():
    tokens_b64 = os.environ.get("GARMIN_TOKENS", "")
    if tokens_b64:
        try:
            garth.resume(base64.b64decode(tokens_b64).decode())
            client = Garmin()
            client.login()
            print("Authenticated via stored tokens")
            return client
        except Exception as e:
            print(f"Token auth failed ({e}), falling back to email/password")

    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email or not password:
        sys.exit("Set GARMIN_TOKENS or GARMIN_EMAIL + GARMIN_PASSWORD env vars")

    client = Garmin(email=email, password=password)
    client.login()
    print("Authenticated via email/password")
    return client


def estimate_tss(duration_secs, avg_hr, sport_type):
    """Estimate TSS proxy from duration and HR. Rough but good enough for CTL/ATL trends."""
    if not duration_secs or duration_secs < 60:
        return 0
    hours = duration_secs / 3600
    if avg_hr and avg_hr > 60:
        hr_ratio = min(avg_hr / 150.0, 1.5)
        return hours * (hr_ratio ** 2) * 100
    # Fallback by sport
    defaults = {"swimming": 60, "open_water_swimming": 65, "running": 70,
                "cycling": 60, "virtual_ride": 55}
    for key, val in defaults.items():
        if key in (sport_type or "").lower():
            return hours * val
    return hours * 50


def fetch_activities(client, start_date, end_date):
    print(f"Fetching activities {start_date} → {end_date}...")
    raw = client.get_activities_by_date(start_date, end_date)
    activities = []
    for a in raw:
        sport = (a.get("activityType") or {}).get("typeKey", "other")
        duration = int(a.get("duration") or 0)
        avg_hr = a.get("averageHR") or 0
        start_time = (a.get("startTimeLocal") or "").replace(" ", "T")
        tss = estimate_tss(duration, avg_hr, sport)
        activities.append({
            "name": a.get("activityName") or "Training",
            "sport_type": sport,
            "start_date_local": start_time,
            "moving_time": duration,
            "distance": a.get("distance") or 0,
            "total_elevation_gain": a.get("elevationGain") or 0,
            "average_speed": a.get("averageSpeed") or 0,
            "calories": a.get("calories") or 0,
            "icu_training_load": round(tss, 1),
            "average_hr": avg_hr,
            "max_hr": a.get("maxHR") or 0,
            "pr_count": 0,
        })
    activities.sort(key=lambda x: x["start_date_local"])
    print(f"  {len(activities)} activities")
    return activities


def fetch_wellness(client, days=30):
    print(f"Fetching wellness data ({days} days)...")
    today = datetime.date.today()
    wellness = {}

    for i in range(days):
        d = today - datetime.timedelta(days=i)
        ds = d.isoformat()
        day = {}

        try:
            hrv = client.get_hrv_data(ds)
            if hrv and "hrvSummary" in hrv:
                v = hrv["hrvSummary"].get("lastNight")
                if v:
                    day["hrv"] = v
        except Exception:
            pass

        try:
            sleep = client.get_sleep_data(ds)
            if sleep and "dailySleepDTO" in sleep:
                s = sleep["dailySleepDTO"]
                secs = s.get("sleepTimeSeconds")
                if secs:
                    day["sleep_secs"] = secs
                score_obj = (s.get("sleepScores") or {}).get("overall") or {}
                score = score_obj.get("value")
                if score:
                    day["sleep_score"] = score
        except Exception:
            pass

        try:
            rhr = client.get_resting_heart_rate(ds)
            if rhr:
                metrics = (rhr.get("allMetrics") or {}).get("metricsMap") or {}
                rhr_list = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
                if rhr_list:
                    day["resting_hr"] = rhr_list[0].get("value")
        except Exception:
            pass

        try:
            bb = client.get_body_battery(ds, ds)
            if bb:
                charged = [x.get("charged", 0) for x in bb if x.get("charged")]
                if charged:
                    day["body_battery"] = max(charged)
        except Exception:
            pass

        try:
            stress = client.get_stress_data(ds)
            if stress:
                avg = stress.get("avgStressLevel") or stress.get("overallStressLevel")
                if avg and avg > 0:
                    day["stress"] = avg
        except Exception:
            pass

        try:
            steps = client.get_steps_data(ds, ds)
            if steps:
                total = sum(x.get("steps", 0) for x in steps)
                if total:
                    day["steps"] = total
        except Exception:
            pass

        if day:
            wellness[ds] = day

        time.sleep(0.25)

    print(f"  {len(wellness)} days with data")
    return wellness


def compute_fitness(activities, days=90):
    """Compute CTL/ATL/TSB from activity training loads using EMA."""
    today = datetime.date.today()
    daily = {}
    for a in activities:
        d = (a.get("start_date_local") or "")[:10]
        if d:
            daily[d] = daily.get(d, 0) + (a.get("icu_training_load") or 0)

    ctl, atl = 0.0, 0.0
    dates = [(today - datetime.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    for ds in dates:
        load = daily.get(ds, 0)
        ctl += (load - ctl) / 42
        atl += (load - atl) / 7

    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}


def main():
    client = login()

    today = datetime.date.today()
    start_90d = (today - datetime.timedelta(days=90)).isoformat()

    activities = fetch_activities(client, start_90d, today.isoformat())
    wellness = fetch_wellness(client, days=30)
    fitness = compute_fitness(activities)
    print(f"Fitness: CTL={fitness['ctl']}, ATL={fitness['atl']}, TSB={fitness['tsb']}")

    output = {
        "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
        "activities": activities,
        "wellness": wellness,
        "fitness": fitness,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "data.json")
    with open(out_path, "w") as f:
        json.dump(output, f)

    print(f"Written data.json — {len(activities)} acts, {len(wellness)} wellness days")


if __name__ == "__main__":
    main()
