"""upload_buffer.py — Post relax-sound shorts to TikTok via Buffer GraphQL API.

Flow:
  1. Upload video to catbox.moe (free, anonymous, public direct URL)
  2. Call Buffer createPost mutation with the video URL + TikTok channel ID

Requires env vars:
  BUFFER_API_KEY              — Buffer API key
  BUFFER_TIKTOK_CHANNEL_ID   — (optional) auto-detected from organization

Non-fatal: if Buffer/catbox fails, YouTube pipeline continues normally.
"""

import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BUFFER_GQL    = "https://api.buffer.com/graphql"
CATBOX_URL    = "https://catbox.moe/user/api.php"
ORG_ID        = "69f49c408c5763cde0019a5b"

_CAPTION_MAX  = 2200
_CORE_TAGS    = [
    "RelaxSound", "ASMR", "SleepSounds",
    "RelaxingMusic", "Meditation", "Chill",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gql(key: str, query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        BUFFER_GQL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Buffer GraphQL error: {data['errors']}")
    return data.get("data", {})


def _get_tiktok_channel_id(key: str) -> str | None:
    """Return TikTok channel ID. Uses env var if set, else queries Buffer."""
    env_id = os.environ.get("BUFFER_TIKTOK_CHANNEL_ID", "").strip()
    if env_id:
        return env_id

    query = """
    query GetChannels($input: ChannelsInput!) {
      channels(input: $input) { id service name }
    }
    """
    try:
        data = _gql(key, query, {"input": {"organizationId": ORG_ID}})
        for ch in data.get("channels", []):
            if ch.get("service") == "tiktok":
                logger.info(f"TikTok channel: {ch['name']} ({ch['id']})")
                return ch["id"]
        logger.warning("No TikTok channel found in Buffer")
    except Exception as e:
        logger.warning(f"Could not fetch Buffer channels: {e}")
    return None


def _upload_to_catbox(video_path: Path) -> str | None:
    """Upload video to catbox.moe and return direct URL."""
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 200:
        logger.warning(f"Video too large for catbox ({size_mb:.0f} MB > 200 MB limit)")
        return None

    logger.info(f"Uploading to catbox.moe ({size_mb:.1f} MB)...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                CATBOX_URL,
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (video_path.name, f, "video/mp4")},
                timeout=300,
            )
        if r.status_code == 200 and r.text.startswith("https://"):
            url = r.text.strip()
            logger.info(f"Catbox URL: {url}")
            return url
        logger.warning(f"Catbox upload failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.warning(f"Catbox upload error: {e}")
    return None


def _build_caption(variant: dict) -> str:
    name     = variant.get("name", "")
    subtitle = variant.get("subtitle", "")
    tags     = variant.get("tags", [])
    variant_tags = [t.replace(" ", "") for t in tags[:8]]
    all_tags = " ".join(f"#{t}" for t in (variant_tags + _CORE_TAGS))
    return f"{name} - {subtitle}\n\n{all_tags}"[:_CAPTION_MAX]


# ── Main function ─────────────────────────────────────────────────────────────

def post_short_to_tiktok(video_path: Path, variant: dict) -> bool:
    """Post a short video to TikTok via Buffer. Returns True on success."""
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not key:
        logger.info("BUFFER_API_KEY not set — TikTok post skipped")
        return False

    if not video_path.exists():
        logger.warning(f"Video not found for Buffer: {video_path}")
        return False

    try:
        channel_id = _get_tiktok_channel_id(key)
        if not channel_id:
            return False

        video_url = _upload_to_catbox(video_path)
        if not video_url:
            return False

        caption = _build_caption(variant)
        title   = variant.get("name", "")[:150]

        mutation = """
        mutation CreatePost($input: CreatePostInput!) {
          createPost(input: $input) {
            ... on Post {
              id
              status
              dueAt
            }
          }
        }
        """

        variables = {
            "input": {
                "channelId": channel_id,
                "text": caption,
                "mode": "shareNow",
                "schedulingType": "automatic",
                "assets": {
                    "videos": [{"url": video_url}]
                },
                "metadata": {
                    "tiktok": {"title": title}
                },
            }
        }

        logger.info(f"Creating Buffer post for TikTok...")
        data = _gql(key, mutation, variables)
        post = data.get("createPost", {})
        post_id = post.get("id", "?")
        status  = post.get("status", "?")
        logger.info(f"TikTok post created via Buffer: id={post_id} status={status}")
        return True

    except Exception as e:
        logger.warning(f"Buffer/TikTok post failed (non-fatal): {e}")
        return False
