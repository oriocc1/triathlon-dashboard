#!/usr/bin/env python3
"""
Run this locally once to get Strava tokens with activity:read_all scope.
Your current tokens only have 'scope: read' which won't return activities.

Usage:
    pip install requests
    python scripts/auth_strava.py
"""
import sys
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

CLIENT_ID     = input("Client ID (261926): ").strip() or "261926"
CLIENT_SECRET = input("Client Secret: ").strip()

AUTH_URL = (
    f"https://www.strava.com/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri=http://localhost:8888"
    f"&response_type=code"
    f"&scope=activity:read_all"
)

code_holder = {}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code_holder["code"] = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h1>Done! You can close this tab and go back to the terminal.</h1>")
    def log_message(self, *args):
        pass

print("\nOpening Strava in your browser — click Authorize...")
webbrowser.open(AUTH_URL)
print("Waiting for authorization...")
HTTPServer(("localhost", 8888), Handler).handle_request()

code = code_holder.get("code")
if not code:
    sys.exit("No authorization code received. Try again.")

r = requests.post("https://www.strava.com/oauth/token", data={
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code":          code,
    "grant_type":    "authorization_code",
})
r.raise_for_status()
tokens = r.json()

print("\n" + "=" * 64)
print("Add these 3 secrets to your GitHub repo:")
print("Repo → Settings → Secrets → Actions → New repository secret")
print("=" * 64)
print(f"STRAVA_CLIENT_ID      =  {CLIENT_ID}")
print(f"STRAVA_CLIENT_SECRET  =  {CLIENT_SECRET}")
print(f"STRAVA_REFRESH_TOKEN  =  {tokens['refresh_token']}")
print("=" * 64)
print(f"\nScope granted: {tokens.get('scope')}")
print("These tokens don't expire — you only need to do this once.")
