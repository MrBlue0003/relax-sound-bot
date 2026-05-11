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
    "#NatureTherapy #HealingMusic #10Hours #LongVideo #AmbientSounds #NoAds"
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


_INTRO_S   = 8           # seconds
_CONTENT_S = 4 * 3600   # 4 hours of visuals
_BLACK_S   = 7 * 3600   # 7 hours black screen
_TOTAL_S   = _INTRO_S + _CONTENT_S + _BLACK_S  # 39 608 s


def _fmt_ts(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _make_chapters(sound_name: str = "") -> str:
    """Generate chapters that reflect the real 11h structure:
    8s intro → 4h visuals → 7h black screen.
    """
    label = sound_name if sound_name else "Ambient sounds"
    lines = [f"00:00:00 - Intro"]
    lines.append(f"{_fmt_ts(_INTRO_S)} - {label} begins")
    for hour in range(1, 4):
        lines.append(f"{_fmt_ts(_INTRO_S + hour * 3600)} - Hour {hour}")
    lines.append(
        f"{_fmt_ts(_INTRO_S + _CONTENT_S)} - Screen turns black — audio continues"
    )
    for hour in range(1, 8):
        lines.append(f"{_fmt_ts(_INTRO_S + _CONTENT_S + hour * 3600)} - Still playing...")
    lines.append(f"{_fmt_ts(_TOTAL_S)} - End")
    return "\n".join(lines)


def _upload_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    """Set a custom thumbnail on an already-uploaded video."""
    try:
        media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        logger.info(f"Thumbnail uploaded for video {video_id}")
    except Exception as e:
        logger.warning(f"Thumbnail upload failed (non-fatal): {e}")


def upload_long_video(
    video_path: Path,
    variant: dict,
    thumbnail_path: Path | None = None,
) -> str:
    """Upload a long ambient video to YouTube. Returns video_id."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    title    = variant["title"]
    subtitle = variant.get("subtitle", "")
    tags_base = variant.get("tags", [])
    category = variant.get("category", "")
    sound_name = variant.get("name", title)

    # Clean title — ensure it stays under 100 chars
    yt_title = title
    if len(yt_title) > 100:
        yt_title = yt_title[:97] + "…"

    # Chapters reflecting real structure
    chapters = _make_chapters(sound_name)

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
        f"🎬 Video Structure (11 hours total)\n"
        f"• 0:00:00 → 0:00:08  — Short intro\n"
        f"• 0:00:08 → 4:00:08  — Ambient visuals + seamless audio loop\n"
        f"• 4:00:08 → 11:00:08 — Black screen — audio continues all night\n\n"
        f"💡 Tip: Start the video and let your screen turn off naturally.\n"
        f"   The sound keeps playing for the full 11 hours.\n\n"
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
            "relaxing sounds", "sleep sounds", "ASMR", "11 hours",
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
            if thumbnail_path and thumbnail_path.exists():
                _upload_thumbnail(youtube, video_id, thumbnail_path)
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
