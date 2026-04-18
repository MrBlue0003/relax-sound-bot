"""
main.py — Relax Sound Bot orchestrator.

Flow:
  1. Pick next variant (7-category weekly rotation, 3 posts/day)
  2. Download ambient video from Pixabay (loops to 120s)
  3. Fallback: image + ffmpeg synthetic audio if no video found
  4. Assemble 120-second vertical video (1080x1920) with text overlay
  5. Upload to Relax Sound YouTube channel
  6. Cleanup temp files

Scheduling:
  - 7 categories × 6 variants each = 42 variants
  - 3 posts/day × 7 days = 21 slots per week
  - Each day all 3 posts share the same category
  - Week N shifts which category appears on which day: (day_idx + week_num) % 7
  - Variant within category: (slot_in_day + week_num * 3) % num_variants
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
import scripts.monthly_compilation as monthly_compilation


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


def pick_variant() -> tuple[dict, int]:
    """Pick next variant using 7-category weekly rotation.
    Returns (variant, slot_in_day) where slot_in_day is 0/1/2.
    """
    with open(config.SOUNDS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    categories = data["categories"]

    upload_count = 0
    if config.UPLOADED_FILE.exists():
        with open(config.UPLOADED_FILE, encoding="utf-8") as f:
            log = json.load(f)
        upload_count = len(log.get("uploads", []))

    # 21 slots per week (7 days × 3 posts/day)
    week_num = upload_count // 21
    slot_in_week = upload_count % 21
    day_idx = slot_in_week // 3       # 0–6: which day of the week
    slot_in_day = slot_in_week % 3    # 0–2: which post of the day (used as video skip offset)

    # Rotate which category appears on which day each week
    cat_idx = (day_idx + week_num) % len(categories)
    category = categories[cat_idx]

    # Rotate which variant within the category each week
    var_idx = (slot_in_day + week_num * 3) % len(category["variants"])
    variant = dict(category["variants"][var_idx])
    variant["category_id"] = category["id"]

    logger.info(
        f"Upload #{upload_count + 1} | Week {week_num + 1} | "
        f"Day {day_idx + 1}/7 | Slot {slot_in_day + 1}/3 | "
        f"Category: {category['label']} | Variant: {variant['name']}"
    )
    return variant, slot_in_day


def get_work_dir(timestamp: str) -> Path:
    if os.name == "nt":
        work_dir = Path(f"E:/temp/rs/{timestamp}")
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
        variant, slot_in_day = pick_variant()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work_dir = get_work_dir(timestamp)

        video_path = work_dir / "clip.mp4"
        image_path = work_dir / "bg.jpg"
        media_path = None

        # slot_in_day (0/1/2) is used as skip offset so each daily post
        # picks a different video/image even when queries are similar
        video_queries = variant.get("video_queries", [])
        if video_queries:
            logger.info(f"Searching Pixabay videos for: {video_queries} (skip={slot_in_day})")
            media_path = download_video_with_fallbacks(
                video_queries, video_path, config.PIXABAY_API_KEY, skip=slot_in_day
            )

        if not media_path:
            logger.info("No video found — falling back to image + generated audio")
            image_queries = variant.get("image_queries", [variant["name"]])
            media_path = download_image_with_fallbacks(
                image_queries, image_path, config.PIXABAY_API_KEY, skip=slot_in_day
            )

        if not media_path:
            logger.error(f"Could not download any media for: {variant['name']}")
            return 1

        safe_name = variant["name"].lower().replace(" ", "_")
        output_path = work_dir / f"relax_{timestamp}_{safe_name}.mp4"
        build_video(variant, media_path, output_path, duration=config.VIDEO_DURATION)

        video_id = upload_video(output_path, variant)

        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info("=" * 60)
        logger.info("  SUCCESS!")
        logger.info(f"  https://www.youtube.com/watch?v={video_id}")
        logger.info(f"  Completed in {elapsed:.0f}s")
        logger.info("=" * 60)

        shutil.rmtree(work_dir, ignore_errors=True)

        # Monthly Best Of compilation — runs automatically on day 1-3 of each month
        if monthly_compilation.should_run(config.UPLOADED_FILE):
            logger.info("Monthly Best Of compilation triggered")
            try:
                comp_id = monthly_compilation.run(
                    config.UPLOADED_FILE,
                    config.OUTPUT_DIR,
                )
                if comp_id:
                    logger.info(f"Compilation: https://www.youtube.com/watch?v={comp_id}")
            except Exception as comp_err:
                logger.error(
                    f"Monthly compilation failed (non-fatal): {comp_err}\n"
                    f"{traceback.format_exc()}"
                )

        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
