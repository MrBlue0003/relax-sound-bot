"""upload.py — Upload relaxation short to the Relax Sound YouTube channel."""
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def get_youtube_client():
    """Authenticate via refresh token (server/CI mode)."""
    if not config.YOUTUBE_REFRESH_TOKEN:
        raise RuntimeError(
            "YOUTUBE_REFRESH_TOKEN not set. Run get_token.py locally first."
        )
    if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env"
        )

    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=config.YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(google.auth.transport.requests.Request())
    logger.info("Authenticated via YOUTUBE_REFRESH_TOKEN")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _verify_channel(youtube) -> tuple[str, str]:
    """Verify we're uploading to the correct channel."""
    resp = youtube.channels().list(part="snippet,id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this account.")

    channel_id = items[0]["id"]
    channel_name = items[0]["snippet"]["title"]
    logger.info(f"Active channel: {channel_name} (ID: {channel_id})")

    expected = config.YOUTUBE_CHANNEL_ID
    if expected and expected != channel_id:
        raise RuntimeError(
            f"Wrong channel! Got '{channel_name}' ({channel_id}), "
            f"expected ID '{expected}'. "
            f"Re-run get_token.py and select the Relax Sound brand account."
        )
    return channel_id, channel_name


def upload_video(video_path: Path, variant: dict) -> str:
    """Upload video to YouTube. Returns video_id."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    name = variant["name"]
    subtitle = variant["subtitle"]
    tags_base = variant.get("tags", [])
    tags = list(set(tags_base + [
        "relaxing sounds", "sleep sounds", "ASMR", "shorts",
        "relax", "meditation", "ambient sounds", "nature sounds",
    ]))

    title = f"{name} \u2022 {subtitle} #Shorts"
    if len(title) > 100:
        title = title[:97] + "\u2026"

    hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags_base[:8])
    description = (
        f"\ud83c\udfb5 {name}\n"
        f"{subtitle}\n\n"
        f"{hashtags} #shorts #relaxingsounds #sleepsounds #ASMR #meditation\n\n"
        f"\ud83d\udd0a Turn on sound for the full experience!\n"
        f"\ud83c\udf3f Subscribe for daily relaxation sounds."
    )

    youtube = get_youtube_client()
    _verify_channel(youtube)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:30],
            "categoryId": "22",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=256 * 1024,
    )

    logger.info(f"Uploading: {video_path.name}")
    logger.info(f"Title: {title}")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")

            video_id = response["id"]
            logger.info(f"Upload complete! https://www.youtube.com/watch?v={video_id}")
            _record_upload(video_id, title, variant)
            return video_id

        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _record_upload(video_id: str, title: str, variant: dict) -> None:
    f = config.UPLOADED_FILE
    data: dict = {"uploads": []}
    if f.exists():
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)

    data["uploads"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "category_id": variant.get("category_id", ""),
        "variant_id": variant.get("id", ""),
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    })

    with open(f, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
    logger.info(f"Recorded in {f}")
