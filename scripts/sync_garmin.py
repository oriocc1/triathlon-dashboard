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
    sys.exit("Run: pip install requests")


def get_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}.\n"
            f"Set it before running, for example:\n"
            f"  set {name}=<value>  # Windows PowerShell\n"
            f"  $env:{name}='<value>'  # PowerShell\n"
            f"  export {name}=<value>  # macOS/Linux\n"
        )
    return value


# ── Strava ────────────────────────────────────────────────────────────────────

def fetch_strava_activities(days=90):
    client_id     = get_env("STRAVA_CLIENT_ID")
    client_secret = get_env("STRAVA_CLIENT_SECRET")
    refresh_token = get_env("STRAVA_REFRESH_TOKEN")

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

def fetch_garmin_wellness(days=30):
    try:
        from garminconnect import Garmin
    except ImportError:
        print("WARNING: garminconnect not installed, skipping Garmin")
        return {}

    tokens = os.environ.get("GARMIN_TOKENS", "").strip()
    if not tokens:
        print("WARNING: GARMIN_TOKENS not set, skipping Garmin wellness.")
        return {}

    token_payload = tokens
    try:
        decoded = base64.b64decode(tokens.encode("utf-8"), validate=True).decode("utf-8")
        if decoded and decoded[0] in "[{":
            token_payload = decoded
    except Exception:
        # Not a base64-encoded token payload, use the raw value as path or token data.
        pass

    api = Garmin()
    try:
        api.login(token_payload)
        print("Garmin: logged in via stored GARMIN_TOKENS")
    except Exception as e:
        print(
            "WARNING: Garmin wellness skipped — failed to log in with GARMIN_TOKENS:",
            e,
            "Regenerate GARMIN_TOKENS if needed."
        )
        return {}

    today = datetime.date.today()
    wellness = {}

    print(f"Fetching Garmin wellness ({days} days)...")
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        ds = d.isoformat()
        day = {}

        try:
            hrv = api.get_hrv_data(ds)
            if hrv and "hrvSummary" in hrv:
                v = hrv["hrvSummary"].get("lastNight")
                if v:
                    day["hrv"] = v
        except Exception:
            pass

        try:
            sleep = api.get_sleep_data(ds)
            if sleep and "dailySleepDTO" in sleep:
                s = sleep["dailySleepDTO"]
                secs = s.get("sleepTimeSeconds")
                if secs:
                    day["sleep_secs"] = secs
                score = ((s.get("sleepScores") or {}).get("overall") or {}).get("value")
                if score:
                    day["sleep_score"] = score
        except Exception:
            pass

        try:
            rhr = api.get_resting_heart_rate(ds)
            if rhr:
                metrics = (rhr.get("allMetrics") or {}).get("metricsMap") or {}
                rhr_list = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
                if rhr_list:
                    day["resting_hr"] = rhr_list[0].get("value")
        except Exception:
            pass

        try:
            bb = api.get_body_battery(ds, ds)
            if bb:
                charged = [x.get("charged", 0) for x in bb if x.get("charged")]
                if charged:
                    day["body_battery"] = max(charged)
        except Exception:
            pass

        try:
            stress = api.get_stress_data(ds)
            if stress:
                avg = stress.get("avgStressLevel") or stress.get("overallStressLevel")
                if avg and avg > 0:
                    day["stress"] = avg
        except Exception:
            pass

        try:
            steps = api.get_steps_data(ds, ds)
            if steps:
                total = sum(x.get("steps", 0) for x in steps)
                if total:
                    day["steps"] = total
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
    try:
        wellness = fetch_garmin_wellness(days=30)
    except Exception as e:
        print(f"WARNING: Garmin skipped — {e}")
        wellness = {}
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
    try:
        main()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
