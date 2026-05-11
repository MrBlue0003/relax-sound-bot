"""upload_buffer.py — Post relax-sound shorts to TikTok via Buffer API.

Requires env vars:
  BUFFER_API_KEY              — Buffer personal access token
  BUFFER_TIKTOK_PROFILE_ID   — (optional) TikTok channel ID in Buffer;
                                auto-detected from /profiles if not set.

Non-fatal: if Buffer is not configured or upload fails, the YouTube
pipeline continues normally and a warning is logged.
"""

import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BUFFER_API = "https://api.bufferapp.com/1"

# TikTok caption hard limit
_CAPTION_MAX = 2200

# Core hashtags appended to every TikTok post
_CORE_TAGS = [
    "RelaxSound", "ASMR", "SleepSounds",
    "RelaxingMusic", "Meditation", "Chill",
]


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _get_tiktok_profile_id(key: str) -> str | None:
    """Return TikTok profile ID from Buffer. Uses env var if set."""
    env_id = os.environ.get("BUFFER_TIKTOK_PROFILE_ID", "").strip()
    if env_id:
        return env_id

    try:
        r = requests.get(
            f"{BUFFER_API}/profiles.json",
            headers=_headers(key),
            timeout=15,
        )
        r.raise_for_status()
        for p in r.json():
            if p.get("service") == "tiktok":
                pid = p["id"]
                username = p.get("service_username", "?")
                logger.info(f"TikTok profile found: {pid} (@{username})")
                return pid
        logger.warning("No TikTok profile found in Buffer — connect TikTok in Buffer Channels")
    except Exception as e:
        logger.warning(f"Could not fetch Buffer profiles: {e}")

    return None


def _build_caption(variant: dict) -> str:
    """Build TikTok-optimised caption from variant metadata."""
    name     = variant.get("name", "")
    subtitle = variant.get("subtitle", "")
    tags     = variant.get("tags", [])

    variant_tags = [t.replace(" ", "") for t in tags[:8]]
    all_tags     = " ".join(f"#{t}" for t in (variant_tags + _CORE_TAGS))

    caption = f"{name} — {subtitle}\n\n{all_tags}"
    return caption[:_CAPTION_MAX]


def _try_media_upload(key: str, video_path: Path) -> str | None:
    """Upload video to Buffer media service. Returns media_id or None."""
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                f"{BUFFER_API}/media/upload.json",
                headers=_headers(key),
                files={"file": (video_path.name, f, "video/mp4")},
                timeout=300,
            )
        if r.status_code in (200, 201):
            data = r.json()
            media_id = data.get("id") or data.get("media_id")
            if media_id:
                logger.info(f"Buffer media uploaded: {media_id}")
                return str(media_id)
        logger.debug(f"Buffer media upload returned {r.status_code}: {r.text[:150]}")
    except Exception as e:
        logger.debug(f"Buffer media upload error: {e}")
    return None


def _create_post(
    key: str,
    profile_id: str,
    caption: str,
    video_path: Path,
    media_id: str | None,
) -> bool:
    """Create a Buffer post. Returns True on success."""
    data: dict = {
        "profile_ids[]": profile_id,
        "text": caption,
        "now": "true",
    }
    files = None

    if media_id:
        data["media[id]"] = media_id
        r = requests.post(
            f"{BUFFER_API}/updates/create.json",
            headers=_headers(key),
            data=data,
            timeout=30,
        )
    else:
        # Fallback: attach video file directly in the post request
        with open(video_path, "rb") as f:
            r = requests.post(
                f"{BUFFER_API}/updates/create.json",
                headers=_headers(key),
                data=data,
                files={"media[video]": (video_path.name, f, "video/mp4")},
                timeout=300,
            )

    if r.status_code in (200, 201):
        logger.info("TikTok post created via Buffer successfully")
        return True

    logger.warning(
        f"Buffer post creation failed: HTTP {r.status_code} — {r.text[:250]}"
    )
    return False


def post_short_to_tiktok(video_path: Path, variant: dict) -> bool:
    """Upload a short video to TikTok via Buffer.

    Returns True on success, False if skipped or failed.
    Never raises — caller should treat False as non-fatal.
    """
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not key:
        logger.info("BUFFER_API_KEY not set — TikTok post skipped")
        return False

    if not video_path.exists():
        logger.warning(f"Video not found for Buffer upload: {video_path}")
        return False

    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 500:
        logger.warning(f"Video too large for TikTok via Buffer ({size_mb:.0f} MB > 500 MB)")
        return False

    profile_id = _get_tiktok_profile_id(key)
    if not profile_id:
        return False

    caption = _build_caption(variant)
    logger.info(f"Posting to TikTok via Buffer: {video_path.name} ({size_mb:.1f} MB)")

    try:
        media_id = _try_media_upload(key, video_path)
        return _create_post(key, profile_id, caption, video_path, media_id)
    except Exception as e:
        logger.warning(f"Buffer/TikTok post failed (non-fatal): {e}")
        return False
