"""
One-time script to generate a fresh YouTube OAuth refresh token.

Usage:
    python scripts/get_youtube_token.py

It opens a browser, prompts you to sign into the CORRECT Google account,
then prints the refresh token to copy into your .env file as YOUTUBE_REFRESH_TOKEN.
"""

import os
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()

if not client_id or not client_secret:
    print("ERROR: YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env")
    sys.exit(1)

client_config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
    }
}

print("\n=== YouTube OAuth Re-Authentication ===")
print("A browser window will open. Sign in with the CORRECT Google account")
print("(the one that owns your HorrorShorts57 channel).\n")

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

refresh_token = creds.refresh_token

if not refresh_token:
    print("\nERROR: No refresh token returned. Try revoking app access at")
    print("  https://myaccount.google.com/permissions")
    print("and run this script again.")
    sys.exit(1)

print("\n=== SUCCESS ===")
print("New refresh token:")
print(f"\n  {refresh_token}\n")
print("Update your .env file:")
print(f"  YOUTUBE_REFRESH_TOKEN={refresh_token}")
print("\nAlso update this on Render.com under Environment Variables.")
