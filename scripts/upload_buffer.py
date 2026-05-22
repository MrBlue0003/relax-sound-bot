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

BUFFER_GQL      = "https://api.buffer.com/graphql"
CATBOX_URL      = "https://catbox.moe/user/api.php"
LITTERBOX_URL   = "https://litterbox.catbox.moe/resources/internals/api.php"
NULLPOINTER_URL = "https://0x0.st"
TMPFILES_URL    = "https://tmpfiles.org/api/v1/upload"
ORG_ID          = "69f49c408c5763cde0019a5b"

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
    if not r.ok:
        raise RuntimeError(f"Buffer HTTP {r.status_code}: {r.text[:500]}")
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
    """Upload video to catbox.moe (anonymous) and return direct URL."""
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 200:
        logger.warning(f"Video too large for catbox ({size_mb:.0f} MB > 200 MB limit)")
        return None

    logger.info(f"Uploading to catbox.moe ({size_mb:.1f} MB)...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                CATBOX_URL,
                data={"reqtype": "fileupload", "userhash": ""},
                files={"fileToUpload": (video_path.name, f, "video/mp4")},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=(10, 120),  # fail-fast if catbox is down
            )
        if r.status_code == 200 and r.text.strip().startswith("https://"):
            url = r.text.strip()
            logger.info(f"Catbox URL: {url}")
            return url
        logger.warning(f"Catbox upload failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.warning(f"Catbox upload error: {e}")
    return None


def _upload_to_litterbox(video_path: Path) -> str | None:
    """Upload video to litterbox.catbox.moe (72h temp, no account needed)."""
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 1000:
        logger.warning(f"Video too large for litterbox ({size_mb:.0f} MB > 1000 MB limit)")
        return None

    logger.info(f"Uploading to litterbox.catbox.moe ({size_mb:.1f} MB)...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                LITTERBOX_URL,
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": (video_path.name, f, "video/mp4")},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=300,
            )
        if r.status_code == 200 and r.text.strip().startswith("https://"):
            url = r.text.strip()
            logger.info(f"Litterbox URL: {url}")
            return url
        logger.warning(f"Litterbox upload failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.warning(f"Litterbox upload error: {e}")
    return None


def _upload_to_nullpointer(video_path: Path) -> str | None:
    """Upload video to 0x0.st as final fallback."""
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 512:
        logger.warning(f"Video too large for 0x0.st ({size_mb:.0f} MB > 512 MB limit)")
        return None

    logger.info(f"Uploading to 0x0.st ({size_mb:.1f} MB)...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                NULLPOINTER_URL,
                files={"file": (video_path.name, f, "video/mp4")},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=300,
            )
        if r.status_code == 200 and r.text.strip().startswith("https://"):
            url = r.text.strip()
            logger.info(f"0x0.st URL: {url}")
            return url
        logger.warning(f"0x0.st upload failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.warning(f"0x0.st upload error: {e}")
    return None


def _upload_to_tmpfiles(video_path: Path) -> str | None:
    """Upload to tmpfiles.org. Supports HEAD (Buffer requires this)."""
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > 100:
        logger.warning(f"Video too large for tmpfiles.org ({size_mb:.0f} MB > 100 MB)")
        return None
    logger.info(f"Uploading to tmpfiles.org ({size_mb:.1f} MB)...")
    try:
        with open(video_path, "rb") as f:
            r = requests.post(
                TMPFILES_URL,
                files={"file": (video_path.name, f, "video/mp4")},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=(10, 300),
            )
        if r.status_code == 200:
            j = r.json()
            view_url = j.get("data", {}).get("url", "")
            if view_url:
                dl_url = view_url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)
                logger.info(f"tmpfiles URL: {dl_url}")
                return dl_url
        logger.warning(f"tmpfiles upload failed: {r.status_code} {r.text[:150]}")
    except Exception as e:
        logger.warning(f"tmpfiles upload error: {e}")
    return None


def _upload_video_public(video_path: Path) -> str | None:
    """Try multiple free hosts until one works. Returns public URL or None.

    Order: tmpfiles (HEAD-friendly, Buffer-compatible) → catbox → litterbox → 0x0.
    Buffer requires HEAD/GET access to validate content-length; litterbox/0x0
    return 405 on HEAD which Buffer rejects.
    """
    url = _upload_to_tmpfiles(video_path)
    if url:
        return url
    logger.info("Trying catbox.moe as fallback...")
    url = _upload_to_catbox(video_path)
    if url:
        return url
    logger.info("Trying litterbox.catbox.moe as fallback...")
    url = _upload_to_litterbox(video_path)
    if url:
        return url
    logger.info("Trying 0x0.st as final fallback...")
    return _upload_to_nullpointer(video_path)


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

        video_url = _upload_video_public(video_path)
        if not video_url:
            return False

        caption = _build_caption(variant)
        title   = variant.get("name", "")[:150]

        mutation = """
        mutation CreatePost($input: CreatePostInput!) {
          createPost(input: $input) {
            ... on PostActionSuccess {
              post {
                id
                status
                dueAt
              }
            }
            ... on InvalidInputError { message }
            ... on LimitReachedError { message }
            ... on UnauthorizedError { message }
            ... on UnexpectedError   { message }
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
        result = data.get("createPost", {})
        # Check for error types
        if "message" in result:
            raise RuntimeError(f"Buffer createPost error: {result.get('type','?')} — {result['message']}")
        post = result.get("post", {})
        post_id = post.get("id", "?")
        status  = post.get("status", "?")
        logger.info(f"TikTok post created via Buffer: id={post_id} status={status}")
        return True

    except Exception as e:
        logger.warning(f"Buffer/TikTok post failed (non-fatal): {e}")
        return False
