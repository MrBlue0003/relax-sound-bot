"""
main_long.py — Relax Sound Long Video Bot

Posts 1-hour ambient YouTube videos once per day.
Runs on a separate schedule (daily_long.yml) — does NOT interfere with shorts.

Rotation:
  - 14 variants in long_videos.json
  - Picks next unseen variant based on upload count in logs/uploaded_long.json
  - Cycles indefinitely (repeats after 14 uploads)
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
from scripts.assemble_long import build_long_video
from scripts.upload_long import upload_long_video


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOGS_DIR / "relax_long.log", encoding="utf-8"),
        ],
    )


logger = logging.getLogger("main_long")

LONG_VIDEOS_FILE = config.DATA_DIR / "long_videos.json"
UPLOADED_LONG_FILE = config.LOGS_DIR / "uploaded_long.json"


def pick_long_variant() -> dict:
    """Pick next long video variant using round-robin rotation."""
    with open(LONG_VIDEOS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    variants = data["long_videos"]

    upload_count = 0
    if UPLOADED_LONG_FILE.exists():
        with open(UPLOADED_LONG_FILE, encoding="utf-8") as f:
            log = json.load(f)
        upload_count = len(log.get("uploads", []))

    idx = upload_count % len(variants)
    variant = variants[idx]

    logger.info(
        f"Long video #{upload_count + 1} | "
        f"[{idx + 1}/{len(variants)}] {variant['title']}"
    )
    return variant


def _find_long_variant_by_id(variant_id: str) -> dict:
    """Look up a long video variant by id."""
    with open(LONG_VIDEOS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    for v in data["long_videos"]:
        if v["id"] == variant_id:
            logger.info(f"Forced long variant: {v['title']}")
            return v
    raise ValueError(f"Long variant ID not found: {variant_id!r}")


def get_work_dir(timestamp: str) -> Path:
    if os.name == "nt":
        work_dir = Path(f"E:/temp/rs_long/{timestamp}")
    else:
        work_dir = config.OUTPUT_DIR / f"long_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def main() -> int:
    setup_logging()
    start = datetime.now(timezone.utc)

    logger.info("=" * 60)
    logger.info("  Relax Sound Long Video Bot — Starting")
    logger.info("=" * 60)
    logger.info(f"Started at {start.isoformat()}")

    if not config.PIXABAY_API_KEY:
        logger.error("PIXABAY_API_KEY not set in .env")
        return 1

    try:
        # Allow workflow_dispatch to force a specific variant
        force_id = os.getenv("FORCE_LONG_VARIANT_ID", "").strip()
        if force_id:
            logger.info(f"FORCE_LONG_VARIANT_ID={force_id}")
            variant = _find_long_variant_by_id(force_id)
        else:
            variant = pick_long_variant()

        duration_h = variant.get("duration_hours", 1)
        duration_s = duration_h * 3600

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work_dir  = get_work_dir(timestamp)

        video_path = work_dir / "clip.mp4"
        image_path = work_dir / "bg.jpg"
        media_path = None

        # Download landscape video from Pixabay
        video_queries = variant.get("video_queries", [])
        if video_queries:
            logger.info(f"Searching Pixabay videos: {video_queries}")
            media_path = download_video_with_fallbacks(
                video_queries, video_path, config.PIXABAY_API_KEY, skip=0
            )

        # Fallback to image if no video found
        if not media_path:
            logger.info("No video — falling back to image")
            image_queries = variant.get("image_queries", [variant["title"]])
            media_path = download_image_with_fallbacks(
                image_queries, image_path, config.PIXABAY_API_KEY, skip=0
            )

        if not media_path:
            logger.error(f"Could not download any media for: {variant['title']}")
            return 1

        # Resolve audio file
        audio_path = None
        audio_file = variant.get("audio_file")
        if audio_file:
            audio_path = config.ASSETS_DIR / audio_file
            if audio_path.exists():
                logger.info(f"Audio override: {audio_path.name}")
            else:
                logger.warning(f"audio_file not found: {audio_path} — lavfi fallback")
                audio_path = None

        # Assemble long video
        safe_id   = variant["id"]
        output_path = work_dir / f"long_{safe_id}_{timestamp}.mp4"
        build_long_video(
            media_path=media_path,
            audio_path=audio_path,
            output_path=output_path,
            duration=duration_s,
            title=variant["title"],
        )

        # Upload
        video_id = upload_long_video(output_path, variant)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("=" * 60)
        logger.info("  SUCCESS!")
        logger.info(f"  https://www.youtube.com/watch?v={video_id}")
        logger.info(f"  Completed in {elapsed:.0f}s ({elapsed/60:.1f} min)")
        logger.info("=" * 60)

        shutil.rmtree(work_dir, ignore_errors=True)
        return 0

    except Exception as e:
        logger.error(f"Long video pipeline failed: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
