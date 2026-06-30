#!/usr/bin/env python3
"""
Syncs training data to data.json:
  - Activities  →  Strava API   (runs, rides, swims, etc.)
  - Wellness    →  Garmin Connect (HRV, sleep, body battery, stress, steps)
"""
import os, json, base64, datetime, time, sys

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests garminconnect garth")


# ── Strava ────────────────────────────────────────────────────────────────────

def fetch_strava_activities(days=90):
    client_id     = os.environ["STRAVA_CLIENT_ID"]
    client_secret = os.environ["STRAVA_CLIENT_SECRET"]
    refresh_token = os.environ["STRAVA_REFRESH_TOKEN"]

    print("Refreshing Strava access token...")
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    })
    r.raise_for_status()
    access_token = r.json()["access_token"]
    print(f"  Token OK (scope: {r.json().get('scope', '?')})")

    after = int((datetime.datetime.utcnow() - datetime.timedelta(days=days)).timestamp())

    print(f"Fetching Strava activities (last {days} days)...")
    activities, page = [], 1
    while True:
        r = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after, "per_page": 100, "page": page},
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        activities.extend(batch)
        print(f"  Page {page}: {len(batch)} activities")
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.3)

    print(f"  Total: {len(activities)} activities")

    result = []
    for a in activities:
        duration = int(a.get("moving_time") or 0)
        avg_hr   = a.get("average_heartrate") or 0
        avg_w    = a.get("average_watts") or 0

        # TSS estimate (power > HR > duration fallback)
        if avg_w and duration:
            tss = (duration / 3600) * (avg_w / 200) * 100
        elif avg_hr > 60 and duration:
            tss = (duration / 3600) * ((avg_hr / 150) ** 2) * 100
        else:
            tss = (duration / 3600) * 50

        result.append({
            "name":                 a.get("name") or "Training",
            "sport_type":           a.get("sport_type") or a.get("type") or "other",
            "start_date_local":     (a.get("start_date_local") or "").rstrip("Z"),
            "moving_time":          duration,
            "distance":             a.get("distance") or 0,
            "total_elevation_gain": a.get("total_elevation_gain") or 0,
            "average_speed":        a.get("average_speed") or 0,
            "calories":             a.get("calories") or 0,
            "icu_training_load":    round(tss, 1),
            "average_hr":           avg_hr,
            "max_hr":               a.get("max_heartrate") or 0,
            "pr_count":             a.get("pr_count") or 0,
        })

    result.sort(key=lambda x: x["start_date_local"])
    return result


# ── Garmin (wellness only) ────────────────────────────────────────────────────

def garmin_login():
    try:
        import garth
        from garminconnect import Garmin
    except ImportError:
        sys.exit("Run: pip install garminconnect garth")

    tokens_b64 = os.environ.get("GARMIN_TOKENS", "")
    if tokens_b64:
        try:
            garth.resume(base64.b64decode(tokens_b64).decode())
            client = Garmin()
            client.login()
            print("Garmin: authenticated via stored tokens")
            return client
        except Exception as e:
            print(f"Garmin token auth failed ({e}), trying email/password...")

    email    = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email:
        sys.exit("Set GARMIN_TOKENS or GARMIN_EMAIL + GARMIN_PASSWORD")

    from garminconnect import Garmin
    client = Garmin(email=email, password=password)
    client.login()
    print("Garmin: authenticated via email/password")
    return client


def fetch_garmin_wellness(days=30):
    client = garmin_login()
    today  = datetime.date.today()
    wellness = {}

    print(f"Fetching Garmin wellness ({days} days)...")
    for i in range(days):
        d  = today - datetime.timedelta(days=i)
        ds = d.isoformat()
        day = {}

        try:
            hrv = client.get_hrv_data(ds)
            if hrv and "hrvSummary" in hrv:
                v = hrv["hrvSummary"].get("lastNight")
                if v: day["hrv"] = v
        except Exception:
            pass

        try:
            sleep = client.get_sleep_data(ds)
            if sleep and "dailySleepDTO" in sleep:
                s    = sleep["dailySleepDTO"]
                secs = s.get("sleepTimeSeconds")
                if secs: day["sleep_secs"] = secs
                score = ((s.get("sleepScores") or {}).get("overall") or {}).get("value")
                if score: day["sleep_score"] = score
        except Exception:
            pass

        try:
            rhr = client.get_resting_heart_rate(ds)
            if rhr:
                metrics  = (rhr.get("allMetrics") or {}).get("metricsMap") or {}
                rhr_list = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
                if rhr_list: day["resting_hr"] = rhr_list[0].get("value")
        except Exception:
            pass

        try:
            bb = client.get_body_battery(ds, ds)
            if bb:
                charged = [x.get("charged", 0) for x in bb if x.get("charged")]
                if charged: day["body_battery"] = max(charged)
        except Exception:
            pass

        try:
            stress = client.get_stress_data(ds)
            if stress:
                avg = stress.get("avgStressLevel") or stress.get("overallStressLevel")
                if avg and avg > 0: day["stress"] = avg
        except Exception:
            pass

        try:
            steps = client.get_steps_data(ds, ds)
            if steps:
                total = sum(x.get("steps", 0) for x in steps)
                if total: day["steps"] = total
        except Exception:
            pass

        if day:
            wellness[ds] = day

        time.sleep(0.25)

    print(f"  {len(wellness)} days with wellness data")
    return wellness


# ── CTL / ATL / TSB ──────────────────────────────────────────────────────────

def compute_fitness(activities, days=90):
    today = datetime.date.today()
    daily = {}
    for a in activities:
        d = (a.get("start_date_local") or "")[:10]
        if d: daily[d] = daily.get(d, 0) + (a.get("icu_training_load") or 0)

    ctl, atl = 0.0, 0.0
    for i in range(days):
        ds   = (today - datetime.timedelta(days=days - 1 - i)).isoformat()
        load = daily.get(ds, 0)
        ctl += (load - ctl) / 42
        atl += (load - atl) / 7

    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    activities = fetch_strava_activities(days=90)
    wellness   = fetch_garmin_wellness(days=30)
    fitness    = compute_fitness(activities)

    print(f"Fitness: CTL={fitness['ctl']}, ATL={fitness['atl']}, TSB={fitness['tsb']}")

    output = {
        "synced_at":  datetime.datetime.utcnow().isoformat() + "Z",
        "activities": activities,
        "wellness":   wellness,
        "fitness":    fitness,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "data.json")
    with open(out_path, "w") as f:
        json.dump(output, f)

    print(f"Written data.json — {len(activities)} activities, {len(wellness)} wellness days")


if __name__ == "__main__":
    main()
