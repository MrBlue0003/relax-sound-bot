"""
main.py — Relax Sound Bot orchestrator.

Flow:
  1. Pick next sound theme (sequential, based on upload count)
  2. Download ambient video from Pixabay (loops to 90s)
  3. Fallback: image + ffmpeg anoisesrc if no video found
  4. Assemble 90-second vertical video (1080x1920) with text overlay
  5. Upload to Relax Sound YouTube channel
  6. Cleanup temp files
"""

import json
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import config
from scripts.fetch_media import (
    download_video_with_fallbacks,
    download_image_with_fallbacks,
)
from scripts.assemble import build_video
from scripts.upload import upload_video


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOGS_DIR / "relax_sound.log", encoding="utf-8"),
        ],
    )


logger = logging.getLogger("main")


def pick_theme() -> dict:
    """Pick next theme sequentially based on upload count."""
    with open(config.SOUNDS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    sounds = data["sounds"]

    upload_count = 0
    if config.UPLOADED_FILE.exists():
        with open(config.UPLOADED_FILE, encoding="utf-8") as f:
            log = json.load(f)
        upload_count = len(log.get("uploads", []))

    idx = upload_count % len(sounds)
    theme = sounds[idx]
    logger.info(f"Theme #{idx + 1}/{len(sounds)}: {theme['name']} — {theme['subtitle']}")
    return theme


def get_work_dir(timestamp: str) -> Path:
    """Get a clean working directory for this run."""
    if os.name == "nt":
        work_dir = Path(f"C:/temp/rs/{timestamp}")
    else:
        work_dir = config.OUTPUT_DIR / timestamp
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def main() -> int:
    setup_logging()
    start = datetime.now(timezone.utc)

    logger.info("=" * 60)
    logger.info("  Relax Sound Bot - Starting")
    logger.info("=" * 60)
    logger.info(f"Started at {start.isoformat()}")

    if not config.PIXABAY_API_KEY:
        logger.error("PIXABAY_API_KEY not set in .env")
        return 1

    try:
        # Step 1: Pick theme
        theme = pick_theme()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work_dir = get_work_dir(timestamp)

        # Step 2: Download media
        video_path = work_dir / "clip.mp4"
        image_path = work_dir / "bg.jpg"
        media_path = None

        video_queries = theme.get("video_queries", [])
        if video_queries:
            logger.info(f"Searching Pixabay videos for: {video_queries}")
            media_path = download_video_with_fallbacks(
                video_queries, video_path, config.PIXABAY_API_KEY
            )

        if not media_path:
            logger.info("No video found — falling back to image + generated noise")
            image_queries = theme.get("image_queries", [theme["name"]])
            media_path = download_image_with_fallbacks(
                image_queries, image_path, config.PIXABAY_API_KEY
            )

        if not media_path:
            logger.error(f"Could not download any media for theme: {theme['name']}")
            return 1

        # Step 3: Assemble video
        safe_name = theme["name"].lower().replace(" ", "_")
        output_path = work_dir / f"relax_{timestamp}_{safe_name}.mp4"
        build_video(theme, media_path, output_path, duration=config.VIDEO_DURATION)

        # Step 4: Upload
        video_id = upload_video(output_path, theme)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("=" * 60)
        logger.info("  SUCCESS!")
        logger.info(f"  https://www.youtube.com/watch?v={video_id}")
        logger.info(f"  Completed in {elapsed:.0f}s")
        logger.info("=" * 60)

        # Step 5: Cleanup
        shutil.rmtree(work_dir, ignore_errors=True)
        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
