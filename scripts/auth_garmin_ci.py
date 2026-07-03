#!/usr/bin/env python3
"""
Non-interactive Garmin auth for GitHub Actions.
Reads GARMIN_EMAIL + GARMIN_PASSWORD from env,
generates a token and saves it as GARMIN_TOKENS secret via gh CLI.
"""
import os
import sys
import base64
import tempfile
import subprocess

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit("ERROR: garminconnect not installed. Run: pip install garminconnect")

email        = os.environ.get("GARMIN_EMAIL", "").strip()
password     = os.environ.get("GARMIN_PASSWORD", "").strip()
setup_token  = os.environ.get("SETUP_TOKEN", "").strip()
repo         = os.environ.get("REPO", "").strip()

if not email or not password:
    sys.exit("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD secrets must be set.")

if not setup_token or not repo:
    sys.exit("ERROR: SETUP_TOKEN and REPO must be set.")

print("Authenticating with Garmin Connect...")
try:
    api = Garmin(email=email, password=password)
    api.login()
except Exception as e:
    sys.exit(f"ERROR: Garmin login failed: {e}\n"
             "If your account has MFA enabled, disable it temporarily, run this workflow, then re-enable it.")

with tempfile.TemporaryDirectory() as tmpdir:
    api.client.dump(tmpdir)
    token_path = os.path.join(tmpdir, "garmin_tokens.json")
    try:
        with open(token_path, "r") as f:
            token_data = f.read()
    except FileNotFoundError:
        sys.exit("ERROR: Token file not generated. Garmin may have blocked the login. Wait 15 min and retry.")

if not token_data or token_data.strip() in ('null', '{}', ''):
    sys.exit("ERROR: Token data is empty. Garmin may be rate-limiting. Wait 15 min and retry.")

b64 = base64.b64encode(token_data.encode()).decode()

print("Saving GARMIN_TOKENS secret to repository...")
env = os.environ.copy()
env["GH_TOKEN"] = setup_token

result = subprocess.run(
    ["gh", "secret", "set", "GARMIN_TOKENS", "--repo", repo, "--body", b64],
    env=env,
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    sys.exit(f"ERROR: Failed to save secret via gh CLI:\n{result.stderr}")

print("SUCCESS! GARMIN_TOKENS secret saved.")
print("Garmin wellness data (HRV, sleep, body battery) will now sync automatically.")
