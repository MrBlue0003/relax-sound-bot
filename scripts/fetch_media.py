"""fetch_media.py — Download ambient video clips or images from Pixabay."""
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PIXABAY_VIDEO_API = "https://pixabay.com/api/videos/"
PIXABAY_IMAGE_API = "https://pixabay.com/api/"
MIN_SIZE_KB = 300


def download_video(query: str, output_path: Path, api_key: str,
                   min_size_kb: int = MIN_SIZE_KB,
                   skip: int = 0) -> Path | None:
    """Search Pixabay for a short video clip and download it. Returns Path or None.

    skip: skip the first N valid hits — use slot_in_day (0,1,2) so each daily
          post picks a different clip even when queries are similar.
    """
    params = {
        "key": api_key,
        "q": query,
        "video_type": "all",
        "per_page": 20,
        "safesearch": "true",
    }
    try:
        r = requests.get(PIXABAY_VIDEO_API, params=params, timeout=15)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as e:
        logger.warning(f"Video search failed '{query}': {e}")
        return None

    if not hits:
        logger.warning(f"No video results for '{query}'")
        return None

    # Prefer clips close to 20s duration
    hits_sorted = sorted(hits, key=lambda h: abs(h.get("duration", 99) - 20))

    skipped = 0
    for hit in hits_sorted:
        videos = hit.get("videos", {})
        video = videos.get("medium") or videos.get("small") or videos.get("large")
        if not video:
            continue
        url = video.get("url")
        if not url:
            continue
        # Skip first N valid candidates so each slot gets a different video
        if skipped < skip:
            skipped += 1
            logger.debug(f"Skipping hit (skip={skip}, skipped={skipped}): id={hit.get('id')}")
            continue
        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            tmp = output_path.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            size_kb = tmp.stat().st_size // 1024
            if size_kb < min_size_kb:
                logger.warning(f"Clip too small ({size_kb}KB < {min_size_kb}KB) for '{query}', skip")
                tmp.unlink(missing_ok=True)
                continue
            tmp.rename(output_path)
            logger.info(f"Video downloaded: {output_path.name} ({size_kb}KB, {hit.get('duration')}s) query='{query}'")
            return output_path
        except Exception as e:
            logger.warning(f"Download failed: {e}")
            output_path.with_suffix(".tmp").unlink(missing_ok=True)
            continue

    logger.warning(f"All hits failed for '{query}'")
    return None


def download_video_with_fallbacks(queries: list[str], output_path: Path,
                                   api_key: str, skip: int = 0) -> Path | None:
    """Try each query in order until a video is found.

    skip: passed to download_video so each daily slot gets a different clip.
    """
    for i, q in enumerate(queries):
        label = "primary" if i == 0 else f"fallback #{i}"
        logger.info(f"Trying {label} query: '{q}' (skip={skip})")
        path = download_video(q, output_path, api_key, skip=skip)
        if path:
            return path
        # If skipping caused no results, retry without skip
        if skip > 0:
            logger.info(f"No result with skip={skip}, retrying '{q}' without skip")
            path = download_video(q, output_path, api_key, skip=0)
            if path:
                return path
        time.sleep(0.3)
    return None


def download_image(query: str, output_path: Path, api_key: str,
                   skip: int = 0) -> Path | None:
    """Download a Pixabay image. Returns Path or None."""
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "per_page": 20,
        "safesearch": "true",
        "min_width": 1080,
    }
    try:
        r = requests.get(PIXABAY_IMAGE_API, params=params, timeout=15)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as e:
        logger.warning(f"Image search failed '{query}': {e}")
        return None

    skipped = 0
    for hit in hits:
        url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not url:
            continue
        if skipped < skip:
            skipped += 1
            continue
        try:
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            logger.info(f"Image downloaded: {output_path.name}")
            return output_path
        except Exception:
            continue
    return None


def download_image_with_fallbacks(queries: list[str], output_path: Path,
                                   api_key: str, skip: int = 0) -> Path | None:
    """Try each image query until one works."""
    for q in queries:
        path = download_image(q, output_path, api_key, skip=skip)
        if path:
            return path
        time.sleep(0.2)
    return None


PIXABAY_AUDIO_API = "https://pixabay.com/api/"

def download_audio(query: str, output_path: Path, api_key: str,
                   min_size_kb: int = 50) -> Path | None:
    """Download ambient audio from Pixabay music/sound API. Returns Path or None."""
    params = {
        "key": api_key,
        "q": query,
        "media_type": "music",
        "per_page": 20,
        "safesearch": "true",
    }
    try:
        r = requests.get(PIXABAY_AUDIO_API, params=params, timeout=15)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as e:
        logger.warning(f"Audio search failed '{query}': {e}")
        return None

    if not hits:
        logger.warning(f"No audio results for '{query}'")
        return None

    for hit in hits:
        # Pixabay audio hits have an 'audio' field with the download URL
        url = hit.get("audio") or hit.get("previewURL", "")
        if not url:
            continue
        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            # Check content type is audio
            ct = resp.headers.get("content-type", "")
            if "text/html" in ct or "xml" in ct:
                continue
            tmp = output_path.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            size_kb = tmp.stat().st_size // 1024
            if size_kb < min_size_kb:
                tmp.unlink(missing_ok=True)
                continue
            tmp.rename(output_path)
            logger.info(f"Audio downloaded: {output_path.name} ({size_kb}KB) query='{query}'")
            return output_path
        except Exception as e:
            logger.warning(f"Audio download failed: {e}")
            output_path.with_suffix(".tmp").unlink(missing_ok=True)
            continue

    logger.warning(f"No audio found for '{query}'")
    return None


def download_audio_with_fallbacks(queries: list[str], output_path: Path,
                                   api_key: str) -> Path | None:
    """Try each audio query until one works."""
    for i, q in enumerate(queries):
        label = "primary" if i == 0 else f"fallback #{i}"
        logger.info(f"Trying audio {label}: '{q}'")
        path = download_audio(q, output_path, api_key)
        if path:
            return path
        time.sleep(0.3)
    return None
