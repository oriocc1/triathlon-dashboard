#!/usr/bin/env python3
"""
Run this script ONCE on your local machine to get Garmin OAuth tokens.
Then store the output as the GARMIN_TOKENS secret in your GitHub repo.

Usage:
    pip install garminconnect
    python scripts/auth_garmin.py
"""
import sys
import base64
import tempfile
import os

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit("Run: pip install garminconnect")

print("Garmin Connect — One-time Authentication")
print("=" * 48)
email = input("Garmin email: ").strip()
password = input("Garmin password: ").strip()
print("\nLogging in (you may get an MFA prompt on your phone)...")

api = Garmin(email=email, password=password)
api.login()

with tempfile.TemporaryDirectory() as tmpdir:
    api.client.dump(tmpdir)
    token_json_path = os.path.join(tmpdir, "garmin_tokens.json")
    with open(token_json_path, "r") as f:
        token_data = f.read()

if not token_data or token_data.strip() in ('null', '{}', ''):
    sys.exit(f"ERROR: Token dump is invalid: {token_data!r}\n"
             "This usually means a 429 rate-limit blocked auth. Wait 15 min and retry.")

b64 = base64.b64encode(token_data.encode()).decode()

print("\n" + "=" * 64)
print("SUCCESS!")
print("Update the GARMIN_TOKENS secret in your GitHub repo:")
print("  Repo → Settings → Secrets and variables → Actions")
print("  → Click GARMIN_TOKENS → Update secret")
print("=" * 64)
print(b64)
print("=" * 64)
print("\nTokens auto-refresh — you only need to do this once.")
