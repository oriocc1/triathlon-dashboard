#!/usr/bin/env python3
"""
Run this script ONCE on your local machine to get Garmin OAuth tokens.
Then store the output as the GARMIN_TOKENS secret in your GitHub repo.

Usage:
    pip install garminconnect garth
    python scripts/auth_garmin.py
"""
import sys
import base64

try:
    import garth
    from garminconnect import Garmin
except ImportError:
    sys.exit("Run: pip install garminconnect garth")

print("Garmin Connect — One-time Authentication")
print("=" * 48)
email = input("Garmin email: ").strip()
password = input("Garmin password: ").strip()
print("\nLogging in (you may get an MFA prompt on your phone)...")

client = Garmin(email=email, password=password)
client.login()

tokens = garth.client.dumps()
b64 = base64.b64encode(tokens.encode()).decode()

print("\n" + "=" * 64)
print("SUCCESS!")
print("Add this as the GARMIN_TOKENS secret in your GitHub repo:")
print("  Repo → Settings → Secrets and variables → Actions")
print("  → New repository secret → Name: GARMIN_TOKENS")
print("=" * 64)
print(b64)
print("=" * 64)
print("\nTokens auto-refresh — you only need to do this once.")
