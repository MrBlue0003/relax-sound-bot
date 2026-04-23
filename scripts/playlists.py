"""playlists.py — Auto-manage YouTube playlists for Relax Sound.

Creates one playlist per category (lazily) and adds every uploaded Short to it.
Playlist IDs are cached in data/playlists.json so we never create duplicates.
"""
import json
import logging
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

PLAYLISTS_FILE = config.DATA_DIR / "playlists.json"

# ── Per-category playlist metadata ───────────────────────────────────────────
CAT_PLAYLIST_META = {
    "rain": {
        "title": "🌧️ Rain Sounds | Relax Sound",
        "description": "Relaxing rain sounds for sleep, focus, and stress relief. New videos daily.",
    },
    "forest": {
        "title": "🌿 Forest & Nature Sounds | Relax Sound",
        "description": "Bird songs, wind, and forest sounds for calm, focus, and relaxation.",
    },
    "ocean": {
        "title": "🌊 Ocean & Water Sounds | Relax Sound",
        "description": "Ocean waves, streams, and water sounds for sleep and meditation.",
    },
    "fireplace": {
        "title": "🔥 Fireplace & Cozy Sounds | Relax Sound",
        "description": "Crackling fire and cozy sounds for relaxation and sleep.",
    },
    "meditation": {
        "title": "🧘 Meditation Music | Relax Sound",
        "description": "Healing frequencies, binaural beats, and meditation tones.",
    },
    "deep_sleep": {
        "title": "🌙 Deep Sleep Sounds | Relax Sound",
        "description": "Brown noise, delta waves, and deep sleep sounds for restful nights.",
    },
    "white_noise": {
        "title": "💤 White Noise | Relax Sound",
        "description": "White noise, pink noise, fan sounds, and noise machines for focus and sleep.",
    },
}


def _load_cache() -> dict:
    if PLAYLISTS_FILE.exists():
        with open(PLAYLISTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"playlists": {}}


def _save_cache(data: dict) -> None:
    with open(PLAYLISTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_or_create_playlist(youtube, category_id: str) -> str | None:
    """
    Return the YouTube playlist ID for the given category.
    Creates the playlist if it doesn't exist yet.
    Returns None on error.
    """
    cache = _load_cache()
    playlists = cache.get("playlists", {})

    # Return cached ID if we already have it
    if category_id in playlists:
        return playlists[category_id]

    meta = CAT_PLAYLIST_META.get(category_id)
    if not meta:
        logger.warning(f"No playlist metadata for category '{category_id}'")
        return None

    try:
        body = {
            "snippet": {
                "title": meta["title"],
                "description": meta["description"],
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": "public",
            },
        }
        resp = youtube.playlists().insert(part="snippet,status", body=body).execute()
        playlist_id = resp["id"]
        logger.info(f"Created playlist '{meta['title']}' → {playlist_id}")

        # Cache it
        playlists[category_id] = playlist_id
        cache["playlists"] = playlists
        _save_cache(cache)
        return playlist_id

    except HttpError as e:
        logger.error(f"Failed to create playlist for '{category_id}': {e}")
        return None


def add_to_playlist(youtube, video_id: str, playlist_id: str) -> bool:
    """Add a video to a playlist. Returns True on success."""
    try:
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id,
                },
            }
        }
        youtube.playlistItems().insert(part="snippet", body=body).execute()
        logger.info(f"Added {video_id} to playlist {playlist_id}")
        return True
    except HttpError as e:
        logger.error(f"Failed to add {video_id} to playlist {playlist_id}: {e}")
        return False


def add_video_to_category_playlist(youtube, video_id: str, category_id: str) -> None:
    """High-level: get/create the category playlist and add the video to it."""
    playlist_id = get_or_create_playlist(youtube, category_id)
    if playlist_id:
        add_to_playlist(youtube, video_id, playlist_id)
