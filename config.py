"""config.py — Global configuration for Relax Sound Bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"

for d in (ASSETS_DIR, OUTPUT_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

PIXABAY_API_KEY: str = os.getenv("PIXABAY_API_KEY", "")
YOUTUBE_REFRESH_TOKEN: str = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_CHANNEL_ID: str = os.getenv("YOUTUBE_CHANNEL_ID", "UCz-SmRhL2fMhy68Hd-H4IrA")
YOUTUBE_CLIENT_ID: str = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "")

VIDEO_DURATION: int = int(os.getenv("RS_VIDEO_DURATION", "120"))
UPLOAD_TIMEZONE: str = os.getenv("UPLOAD_TIMEZONE", "Europe/Bucharest")

SOUNDS_FILE = DATA_DIR / "sounds.json"
UPLOADED_FILE = LOGS_DIR / "uploaded.json"
