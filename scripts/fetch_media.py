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
                   min_size_kb: int = MIN_SIZE_KB) -> Path | None:
    """Search Pixabay for a short video clip and download it. Returns Path or None."""
    params = {
        "key": api_key,
        "q": query,
        "video_type": "all",
        "per_page": 15,
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

    for hit in hits_sorted:
        videos = hit.get("videos", {})
        video = videos.get("medium") or videos.get("small") or videos.get("large")
        if not video:
            continue
        url = video.get("url")
        if not url:
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
                                   api_key: str) -> Path | None:
    """Try each query in order until a video is found."""
    for i, q in enumerate(queries):
        label = "primary" if i == 0 else f"fallback #{i}"
        logger.info(f"Trying {label} query: '{q}'")
        path = download_video(q, output_path, api_key)
        if path:
            return path
        time.sleep(0.3)
    return None


def download_image(query: str, output_path: Path, api_key: str) -> Path | None:
    """Download a Pixabay image. Returns Path or None."""
    params = {
        "key": api_key,
        "q": query,
        "image_type": "photo",
        "per_page": 10,
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

    for hit in hits:
        url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not url:
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
                                   api_key: str) -> Path | None:
    """Try each image query until one works."""
    for q in queries:
        path = download_image(q, output_path, api_key)
        if path:
            return path
        time.sleep(0.2)
    return None
