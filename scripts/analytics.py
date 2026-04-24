"""analytics.py — Fetch YouTube video stats and update per-category weights.

Reads logs/uploaded.json, fetches viewCount for each uploaded video via
YouTube Data API v3 (no extra OAuth scope needed), computes average views
per category, then writes data/weights.json.

pick_variant() in main.py reads weights.json to give more upload slots to
categories that perform better, creating a feedback loop over time.

Run: called automatically by the weekly analytics workflow, or manually:
    python scripts/analytics.py
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from scripts.upload import get_youtube_client

logger = logging.getLogger(__name__)

WEIGHTS_FILE = config.DATA_DIR / "weights.json"
MIN_VIDEOS   = 3   # minimum videos per category before adjusting its weight
WEIGHT_MIN   = 0.5
WEIGHT_MAX   = 2.0


def _fetch_stats(youtube, video_ids: list[str]) -> dict[str, int]:
    """Return {video_id: view_count} for a list of IDs (batched 50 at a time)."""
    result = {}
    for i in range(0, len(video_ids), 50):
        batch_ids = ",".join(video_ids[i:i + 50])
        try:
            resp = youtube.videos().list(
                part="statistics", id=batch_ids
            ).execute()
            for item in resp.get("items", []):
                views = int(item["statistics"].get("viewCount", 0))
                result[item["id"]] = views
        except Exception as e:
            logger.warning(f"Stats batch fetch failed: {e}")
    return result


def compute_weights(youtube) -> dict[str, float]:
    """Return {category_id: weight} based on avg views. Empty dict if not enough data."""
    if not config.UPLOADED_FILE.exists():
        logger.info("No uploaded.json found — skipping analytics")
        return {}

    with open(config.UPLOADED_FILE, encoding="utf-8") as f:
        log = json.load(f)

    uploads = log.get("uploads", [])
    if not uploads:
        return {}

    video_ids = [u["video_id"] for u in uploads if u.get("video_id")]
    if not video_ids:
        return {}

    logger.info(f"Fetching stats for {len(video_ids)} videos …")
    stats = _fetch_stats(youtube, video_ids)

    # Group views by category
    cat_views: dict[str, list[int]] = {}
    for u in uploads:
        vid = u.get("video_id")
        cat = u.get("category_id")
        if vid and cat and vid in stats:
            cat_views.setdefault(cat, []).append(stats[vid])

    # Only categories with enough data
    qualified = {
        cat: views
        for cat, views in cat_views.items()
        if len(views) >= MIN_VIDEOS
    }
    if not qualified:
        logger.info("Not enough videos per category yet — keeping equal weights")
        return {}

    cat_avg = {cat: sum(v) / len(v) for cat, v in qualified.items()}
    overall_avg = sum(cat_avg.values()) / len(cat_avg)

    weights = {}
    for cat, avg in cat_avg.items():
        raw = avg / overall_avg if overall_avg > 0 else 1.0
        weights[cat] = round(max(WEIGHT_MIN, min(WEIGHT_MAX, raw)), 3)

    for cat, w in sorted(weights.items(), key=lambda x: -x[1]):
        avg_v = cat_avg[cat]
        n     = len(qualified[cat])
        logger.info(f"  {cat:12s}  avg_views={avg_v:,.0f}  n={n}  weight={w}")

    return weights


def update_weights(youtube) -> None:
    """Compute new weights, merge with existing file, save."""
    new_weights = compute_weights(youtube)

    existing: dict[str, float] = {}
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE, encoding="utf-8") as f:
            existing = json.load(f).get("categories", {})

    # New weights override existing; categories with no data keep old weight
    merged = {**existing, **new_weights}

    out = {
        "updated":    datetime.now(timezone.utc).date().isoformat(),
        "categories": merged,
    }
    with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    logger.info(f"Weights saved → {WEIGHTS_FILE}")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        youtube = get_youtube_client()
        update_weights(youtube)
        return 0
    except Exception as e:
        logger.error(f"Analytics failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
