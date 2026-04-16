"""
get_token.py — One-time YouTube OAuth setup for Relax Sound channel.

Run locally:
    python get_token.py

In the browser that opens, select the Google account that manages
the 'Relax Sound' brand account, then click Allow.

Copy the printed YOUTUBE_REFRESH_TOKEN into your .env file.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")

if not client_id or not client_secret:
    print("ERROR: Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

client_config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
    }
}

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: Run 'pip install -r requirements.txt' first.")
    sys.exit(1)

print("Opening browser for YouTube authentication...")
print("IMPORTANT: Select the account that has access to the 'Relax Sound' channel.")
print()

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

print()
print("=" * 60)
print("SUCCESS! Add this line to your .env file:")
print("=" * 60)
print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
print("=" * 60)
