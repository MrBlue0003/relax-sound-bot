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
    Returns (variant, slot_in_day) where slot_in_day is 0/1/2/3.
    Never repeats a variant that appeared in the last 28 uploads.
    """
    with open(config.SOUNDS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    categories = data["categories"]

    upload_count = 0
    recent_variants: set[str] = set()
    if config.UPLOADED_FILE.exists():
        with open(config.UPLOADED_FILE, encoding="utf-8") as f:
            log = json.load(f)
        uploads = log.get("uploads", [])
        upload_count = len(uploads)
        # Collect variant_ids from last 28 posts (full week cycle at 4/day)
        recent_variants = {
            u["variant_id"] for u in uploads[-28:]
            if u.get("variant_id")
        }

    # 28 slots per week (7 days × 4 posts/day)
    week_num     = upload_count // 28
    slot_in_week = upload_count % 28
    day_idx      = slot_in_week // 4
    slot_in_day  = slot_in_week % 4   # 0-3 → used as Pixabay skip offset

    # Build full flat list of all variants (42 total)
    all_variants = []
    for cat in categories:
        for v in cat["variants"]:
            entry = dict(v)
            entry["category_id"] = cat["id"]
            all_variants.append(entry)

    # Pick candidate via rotation
    base_idx  = upload_count % len(all_variants)
    candidate = all_variants[base_idx]

    # If candidate was recently posted, walk forward to find a fresh one
    if candidate["id"] in recent_variants:
        for offset in range(1, len(all_variants)):
            alt = all_variants[(base_idx + offset) % len(all_variants)]
            if alt["id"] not in recent_variants:
                candidate = alt
                logger.info(f"Skipped recently-posted variant, using: {alt['name']}")
                break

    # Determine category for logging
    cat_label = next(
        (c["label"] for c in categories if c["id"] == candidate["category_id"]),
        candidate["category_id"]
    )

    logger.info(
        f"Upload #{upload_count + 1} | Week {week_num + 1} | "
        f"Slot {slot_in_day + 1}/4 | "
        f"Category: {cat_label} | Variant: {candidate['name']}"
    )
    return candidate, slot_in_day


def _find_variant_by_id(variant_id: str) -> tuple[dict, int]:
    """Look up a variant by its id from sounds.json. Returns (variant, slot_in_day=0)."""
    with open(config.SOUNDS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    for cat in data["categories"]:
        for v in cat["variants"]:
            if v["id"] == variant_id:
                entry = dict(v)
                entry["category_id"] = cat["id"]
                logger.info(f"Forced variant: {entry['name']} (category: {cat['label']})")
                return entry, 0
    raise ValueError(f"Variant ID not found in sounds.json: {variant_id!r}")


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
        # Allow workflow_dispatch to force a specific variant
        force_id = os.getenv("FORCE_VARIANT_ID", "").strip()
        if force_id:
            logger.info(f"FORCE_VARIANT_ID={force_id} — bypassing rotation")
            variant, slot_in_day = _find_variant_by_id(force_id)
        else:
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

        # Resolve optional real audio file (overrides lavfi + video audio)
        audio_path = None
        audio_file = variant.get("audio_file")
        if audio_file:
            audio_path = config.ASSETS_DIR / audio_file
            if audio_path.exists():
                logger.info(f"Audio file override: {audio_path.name}")
            else:
                logger.warning(f"audio_file not found: {audio_path} — using lavfi fallback")
                audio_path = None

        safe_name = variant["name"].lower().replace(" ", "_")
        output_path = work_dir / f"relax_{timestamp}_{safe_name}.mp4"
        build_video(variant, media_path, output_path, duration=config.VIDEO_DURATION,
                    audio_path=audio_path)

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
