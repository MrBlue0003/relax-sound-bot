"""upload_long.py — Upload 1-hour ambient videos to the Relax Sound YouTube channel.

Separate from upload.py (shorts) — different metadata format:
  • No #Shorts in title
  • Long-form description with timestamp chapters
  • Category Music (10) for better recommendation targeting
  • Full tag set for long-form ambient discoverability
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# ── Duration emoji map ────────────────────────────────────────────────────────
_DURATION_EMOJI = {
    "rain":      "🌧️",
    "forest":    "🌿",
    "ocean":     "🌊",
    "fireplace": "🔥",
    "meditation":"🧘",
    "deep_sleep":"🌙",
    "white_noise":"💤",
}

# ── Category hashtags (long-form focused) ────────────────────────────────────
_CATEGORY_HASHTAGS = {
    "rain": (
        "#RainSounds #RainyDay #RainASMR #RainForSleep #RainAndThunder "
        "#RainfallSounds #RainAmbience #HeavyRain #GentleRain #RainNoise "
        "#TropicalRain #SummerRain #RainMeditation #RelaxingRain #RainyNight"
    ),
    "forest": (
        "#ForestSounds #BirdSounds #BirdChirping #NatureSounds #MorningBirds "
        "#ForestAmbience #WoodlandSounds #ForestWalk #NatureASMR #BirdSinging "
        "#ForestMeditation #NatureRelax #BirdCalls #TreeSounds #WildNature"
    ),
    "ocean": (
        "#OceanSounds #WaveSounds #BeachSounds #OceanWaves #SeaSounds "
        "#BeachASMR #OceanRelax #CoastalSounds #TidalWaves #BeachVibes "
        "#OceanMeditation #BeachMeditation #WaveLoops #NatureOcean #BlueMind"
    ),
    "fireplace": (
        "#FireplaceSounds #CracklingFire #CampfireSounds #FireASMR "
        "#CozyFireplace #WinterFireplace #FireplaceAmbience #BonfireSound "
        "#CampfireNight #WoodBurning #CozyVibes #WarmFireplace #FireRelax"
    ),
    "meditation": (
        "#MeditationMusic #HealingFrequencies #TibetanBowls #SoundHealing "
        "#BinauralBeats #ZenMusic #SoundBath #HealingTones #SolfeggioFrequencies "
        "#ThetaWaves #AlphaWaves #CrystalBowls #SoundTherapy #Mindfulness"
    ),
    "deep_sleep": (
        "#DeepSleep #SleepSounds #SleepMusic #InsomniaCure #BetterSleep "
        "#SleepTherapy #SleepMeditation #NightSounds #GoodNightSounds "
        "#DeltaWaves #SleepRelaxation #PowerNap #BabySleep #SoothingNight"
    ),
}

_UNIVERSAL_LONG = (
    "#RelaxingSounds #ASMR #Meditation #NatureSounds #AmbientSound "
    "#ChillVibes #StressRelief #SleepMusic #CalmMusic #Mindfulness "
    "#RelaxingMusic #AnxietyRelief #PeacefulMusic #ZenMusic #LofiChill "
    "#SleepAid #MeditationMusic #BackgroundMusic #FocusMusic #SelfCare "
    "#MentalHealth #Relaxation #InnerPeace #Soundscape #AmbientMusic "
    "#NatureTherapy #HealingMusic #3Hours #LongVideo #AmbientSounds #NoAds"
)

# Extra hashtags for new categories
_CATEGORY_HASHTAGS_EXTRA = {
    "coffee_shop": (
        "#CoffeeShop #CafeAmbience #StudyWithMe #LofiStudy #CoffeeSounds "
        "#WorkFromHome #FocusMusic #CafeNoise #StudySounds #ProductivityMusic "
        "#LofiCafe #WorkSounds #StudyMotivation #DeepFocus #CoffeeVibes"
    ),
}


def _get_youtube_client():
    """Authenticate via refresh token."""
    if not config.YOUTUBE_REFRESH_TOKEN:
        raise RuntimeError("YOUTUBE_REFRESH_TOKEN not set.")
    if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
        raise RuntimeError("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set.")

    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=config.YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(google.auth.transport.requests.Request())
    logger.info("Authenticated via YOUTUBE_REFRESH_TOKEN")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _verify_channel(youtube) -> tuple[str, str]:
    resp = youtube.channels().list(part="snippet,id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this account.")
    channel_id   = items[0]["id"]
    channel_name = items[0]["snippet"]["title"]
    logger.info(f"Active channel: {channel_name} (ID: {channel_id})")
    expected = config.YOUTUBE_CHANNEL_ID
    if expected and expected != channel_id:
        raise RuntimeError(
            f"Wrong channel! Got '{channel_name}' ({channel_id}), "
            f"expected '{expected}'."
        )
    return channel_id, channel_name


def _make_chapters(duration_hours: int) -> str:
    """Generate timestamp chapters string."""
    lines = ["00:00:00 - Start"]
    total_min = duration_hours * 60
    step = 15  # chapter every 15 minutes
    t = step
    while t < total_min:
        h = t // 60
        m = t % 60
        lines.append(f"{h:02d}:{m:02d}:00 - Continuing...")
        t += step
    h = total_min // 60
    m = total_min % 60
    lines.append(f"{h:02d}:{m:02d}:00 - End")
    return "\n".join(lines)


def upload_long_video(video_path: Path, variant: dict) -> str:
    """Upload a long ambient video to YouTube. Returns video_id."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    title    = variant["title"]
    subtitle = variant.get("subtitle", "")
    tags_base = variant.get("tags", [])
    category = variant.get("category", "")
    duration_hours = variant.get("duration_hours", 1)

    # Clean title — ensure it stays under 100 chars
    yt_title = title
    if len(yt_title) > 100:
        yt_title = yt_title[:97] + "…"

    # Build chapters
    chapters = _make_chapters(duration_hours)

    # Hashtags
    cat_tags = _CATEGORY_HASHTAGS.get(category, "") or _CATEGORY_HASHTAGS_EXTRA.get(category, "")
    variant_hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags_base[:15])
    hashtags = f"{_UNIVERSAL_LONG}\n{cat_tags}\n{variant_hashtags}"

    description = (
        f"🎵 {title}\n"
        f"{subtitle}\n\n"
        f"🔊 Turn on sound for the full experience!\n"
        f"🌿 Subscribe for daily relaxation sounds 🔔\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Chapters:\n"
        f"{chapters}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Perfect for:\n"
        f"✓ Deep sleep & insomnia relief\n"
        f"✓ Study & focus\n"
        f"✓ Meditation & yoga\n"
        f"✓ Stress & anxiety relief\n"
        f"✓ Baby sleep\n"
        f"✓ Background ambience\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{hashtags}"
    )

    # Deduplicated tag list
    all_tags = list(dict.fromkeys(
        tags_base + [
            "relaxing sounds", "sleep sounds", "ASMR", "1 hour",
            "ambient sounds", "nature sounds", "stress relief",
            "calm music", "meditation", "sleep music", "background music",
            "focus music", "long video", "no ads",
        ]
    ))

    youtube = _get_youtube_client()
    _verify_channel(youtube)

    body = {
        "snippet": {
            "title": yt_title,
            "description": description,
            "tags": all_tags[:30],
            "categoryId": "10",    # Music — best for ambient/relaxation
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    # Chunked resumable upload — 512KB chunks for large files
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=512 * 1024,
    )

    logger.info(f"Uploading long video: {video_path.name}")
    logger.info(f"Title: {yt_title}")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.info(f"Upload progress: {pct}%")

            video_id = response["id"]
            logger.info(f"Upload complete: https://www.youtube.com/watch?v={video_id}")
            _record_upload(video_id, yt_title, variant)
            return video_id

        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status} — retrying in {wait}s…")
                time.sleep(wait)
            else:
                raise


def _record_upload(video_id: str, title: str, variant: dict) -> None:
    """Append upload record to logs/uploaded_long.json."""
    f = config.LOGS_DIR / "uploaded_long.json"
    data: dict = {"uploads": []}
    if f.exists():
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)

    data["uploads"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "variant_id": variant.get("id", ""),
        "category": variant.get("category", ""),
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    })

    with open(f, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
    logger.info(f"Recorded in {f}")
