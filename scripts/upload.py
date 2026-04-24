"""upload.py — Upload relaxation short to the Relax Sound YouTube channel."""
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


def get_youtube_client():
    """Authenticate via refresh token (server/CI mode)."""
    if not config.YOUTUBE_REFRESH_TOKEN:
        raise RuntimeError(
            "YOUTUBE_REFRESH_TOKEN not set. Run get_token.py locally first."
        )
    if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env"
        )

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
    """Verify we're uploading to the correct channel."""
    resp = youtube.channels().list(part="snippet,id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this account.")

    channel_id = items[0]["id"]
    channel_name = items[0]["snippet"]["title"]
    logger.info(f"Active channel: {channel_name} (ID: {channel_id})")

    expected = config.YOUTUBE_CHANNEL_ID
    if expected and expected != channel_id:
        raise RuntimeError(
            f"Wrong channel! Got '{channel_name}' ({channel_id}), "
            f"expected ID '{expected}'. "
            f"Re-run get_token.py and select the Relax Sound brand account."
        )
    return channel_id, channel_name


# ── Per-category thematic hashtags ───────────────────────────────────────────
_CATEGORY_HASHTAGS = {
    "rain": (
        "#RainSounds #RainyDay #RainASMR #RainVibes #RainNoise #RainingOutside "
        "#RainOnWindow #HeavyRain #ThunderstormSounds #RainRelax #RainAndThunder "
        "#RainForSleeping #RainfallSounds #RainBackground #TropicalRain "
        "#SummerRain #RainMeditation #RainSoundscape #RainyNight #RainLoops"
    ),
    "forest": (
        "#ForestSounds #BirdSounds #BirdChirping #NatureSounds #BirdSinging "
        "#MorningBirds #ForestBirds #WildBirds #BirdWatching #BirdLovers "
        "#BirdLife #SongBirds #ForestAmbience #NatureASMR #WoodlandSounds "
        "#ForestWalk #NatureTherapy #BirdCalls #TreeSounds #WildNature "
        "#ForestMeditation #BirdNature #NatureSoundscape #OutdoorSounds "
        "#Birding #WildlifeSound #ForestRelax #NatureVibes #OrnithoLovers"
    ),
    "ocean": (
        "#OceanSounds #WaveSounds #BeachSounds #OceanWaves #SeaSounds "
        "#BeachASMR #WaterfallSounds #RiverSounds #WaterSounds #OceanRelax "
        "#CoastalSounds #TidalWaves #BeachVibes #OceanAmbience #SeaTherapy "
        "#WaterNoise #CreekSounds #StreamSounds #UnderwaterSounds #TropicalBeach "
        "#OceanMeditation #BeachMeditation #WaveLoops #NatureOcean #BlueMind"
    ),
    "meditation": (
        "#MeditationMusic #432Hz #528Hz #HealingFrequencies #TibetanBowls "
        "#SingingBowls #BinauralBeats #SoundHealing #ChakraHealing #ZenMusic "
        "#MindfulMeditation #GuidedMeditation #SoundBath #HealingTones "
        "#FrequencyHealing #SolfeggioFrequencies #ThetaWaves #AlphaWaves "
        "#DeltaWaves #BrainwaveEntrainment #CrystalBowls #SoundTherapy "
        "#EnergyHealing #SpiritualMusic #AncientTones #VibrationalHealing"
    ),
    "white_noise": (
        "#WhiteNoise #PinkNoise #BrownNoise #WhiteNoiseASMR #NoiseMachine "
        "#FanSound #AirConditioner #SleepNoise #BabySleep #FocusNoise "
        "#ConcentrationSound #StudyNoise #OfficeBackground #StaticNoise "
        "#ColoredNoise #NoiseBlocking #TinnitusMasking #ADHDFocus #SleepAid"
    ),
    "fireplace": (
        "#FireplaceSounds #CracklingFire #CampfireSounds #FireASMR "
        "#CozyFireplace #WinterFireplace #FireplaceAmbience #BonfireSound "
        "#CampfireNight #WoodBurning #CozyVibes #WarmFireplace #FireRelax "
        "#FireplaceMeditation #CabinFireplace #FireAndRain #WoodCrackling "
        "#CozyWinter #Candlelight #FireLoops #HyggeVibes #CozySounds"
    ),
    "deep_sleep": (
        "#DeepSleep #SleepSounds #SleepMusic #InsomniaCure #BetterSleep "
        "#SleepTherapy #SleepMeditation #NightSounds #SleepingMusic "
        "#GoodNightSounds #DeltaWaves #BrainwaveSleep #SleepRelaxation "
        "#PowerNap #NapMusic #SleepASMR #BabySleep #SleepNoises "
        "#KidsAsleep #SoothingNight #NightRelax #SleepStories #DreamSound"
    ),
}

# ── Universal viral hashtags ──────────────────────────────────────────────────
_UNIVERSAL_HASHTAGS = (
    "#Shorts #RelaxingSounds #ASMR #Meditation #NatureSounds "
    "#AmbientSound #ChillVibes #StressRelief #SleepMusic #CalmMusic "
    "#Mindfulness #RelaxingMusic #AnxietyRelief #PeacefulMusic #ZenMusic "
    "#LofiChill #RelaxAndUnwind #SleepAid #MeditationMusic #BackgroundMusic "
    "#FocusMusic #SelfCare #MentalHealth #ChillOut #Calming #Soothing "
    "#Relaxation #DeStress #InnerPeace #MindBody #Wellness #Soundscape "
    "#AmbientMusic #Tranquil #NatureTherapy #HealingMusic #YogaMusic "
    "#BreathingExercise #MindfulLiving #PositiveVibes #GoodVibesOnly "
    "#TikTokRelax #Trending #Viral #SleepTok #MeditationTok #ASMRCommunity "
    "#RelaxationStation #ChillZone #SoundTherapy #NatureLovers #Peaceful"
)


# ── Per-category metadata ─────────────────────────────────────────────────────
_CAT_EMOJI = {
    "rain":       "🌧️",
    "forest":     "🌿",
    "ocean":      "🌊",
    "fireplace":  "🔥",
    "meditation": "🧘",
    "deep_sleep": "🌙",
    "white_noise":"💤",
}

# Benefit phrase used in title: "{emoji} {name} for {benefit} #Shorts"
_CAT_BENEFIT = {
    "rain":       "Deep Sleep",
    "forest":     "Focus & Calm",
    "ocean":      "Relaxation",
    "fireplace":  "Cozy Vibes",
    "meditation": "Meditation",
    "deep_sleep": "Deep Sleep",
    "white_noise":"Focus",
}

_CAT_DESC_HOOKS = {
    "rain":       "Close your eyes and let the rain wash away your stress.",
    "forest":     "Breathe in the peaceful sounds of nature.",
    "ocean":      "Let the waves carry you to a place of calm.",
    "fireplace":  "Get cozy and let the fire warm your soul.",
    "meditation": "Clear your mind and find your inner peace.",
    "deep_sleep": "Drift off into deep, restful sleep.",
    "white_noise":"Find your focus and block out distractions.",
}

# Pinned comment per category — numbered poll format drives replies & watch time
_CAT_COMMENTS = {
    "rain":
        "🌧️ What do you use rain sounds for?\n"
        "1️⃣ Fall asleep\n"
        "2️⃣ Study & focus\n"
        "3️⃣ Stress relief\n"
        "👇 Drop your number below!\n\n"
        "Follow for 4 new sounds every day 🔔",
    "forest":
        "🌿 When do you listen to nature sounds?\n"
        "1️⃣ While working\n"
        "2️⃣ Before sleep\n"
        "3️⃣ During meditation\n"
        "👇 Comment your number!\n\n"
        "Follow for daily relaxation sounds 🔔",
    "ocean":
        "🌊 Ocean waves help you...\n"
        "1️⃣ Fall asleep faster\n"
        "2️⃣ Focus & study\n"
        "3️⃣ Reduce anxiety\n"
        "👇 Which one is you?\n\n"
        "Follow for 4 new sounds every day 🔔",
    "fireplace":
        "🔥 You're listening to this because...\n"
        "1️⃣ Getting cozy tonight\n"
        "2️⃣ Can't sleep\n"
        "3️⃣ Just want to relax\n"
        "👇 Tell me below!\n\n"
        "Follow for daily relaxation sounds 🔔",
    "meditation":
        "🧘 How do you meditate?\n"
        "1️⃣ With music or sound\n"
        "2️⃣ In total silence\n"
        "3️⃣ I'm just starting out\n"
        "👇 Drop your number!\n\n"
        "Follow for 4 new sounds every day 🔔",
    "deep_sleep":
        "🌙 What keeps you awake at night?\n"
        "1️⃣ Anxiety & stress\n"
        "2️⃣ Racing thoughts\n"
        "3️⃣ Can't switch off\n"
        "👇 You're not alone — comment below!\n\n"
        "Follow for daily sleep sounds 🔔",
    "white_noise":
        "💤 White noise helps you...\n"
        "1️⃣ Focus & study\n"
        "2️⃣ Block out distractions\n"
        "3️⃣ Fall asleep faster\n"
        "👇 Which one?\n\n"
        "Follow for 4 new sounds every day 🔔",
}


def _auto_like(youtube, video_id: str) -> None:
    """Like the video with the channel owner account — small engagement signal."""
    try:
        youtube.videos().rate(id=video_id, rating="like").execute()
        logger.info(f"Auto-liked: {video_id}")
    except HttpError as e:
        logger.warning(f"Could not auto-like: {e}")


def _post_comment(youtube, video_id: str, category_id: str) -> None:
    """Post a channel-owner comment on the video to drive engagement."""
    text = _CAT_COMMENTS.get(category_id, "🔔 Follow for daily relaxation sounds! 👇")
    try:
        resp = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text}
                    },
                }
            },
        ).execute()
        comment_id = resp["snippet"]["topLevelComment"]["id"]
        logger.info(f"Comment posted: {comment_id}")
    except HttpError as e:
        # Non-fatal — video still uploaded successfully
        logger.warning(f"Could not post comment: {e}")


def upload_video(video_path: Path, variant: dict) -> str:
    """Upload video to YouTube. Returns video_id."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    from scripts.playlists import add_video_to_category_playlist

    name        = variant["name"]
    subtitle    = variant.get("subtitle", "")
    tags_base   = variant.get("tags", [])
    category_id = variant.get("category_id", "")
    emoji       = _CAT_EMOJI.get(category_id, "🎵")
    benefit     = _CAT_BENEFIT.get(category_id, "Relaxation")
    hook_line   = _CAT_DESC_HOOKS.get(category_id, "Relax and unwind.")

    # Build thematic tags list (deduplicated)
    all_tags = list(dict.fromkeys(
        tags_base + [
            "relaxing sounds", "sleep sounds", "ASMR", "shorts",
            "relax", "meditation", "ambient sounds", "nature sounds",
            "stress relief", "calm music", "chillout", "focus music",
            "sleep music", "background music", "white noise", "sound therapy",
        ]
    ))

    # Title format: "{emoji} {name} for {benefit} #Shorts"
    # More searchable than old "name • subtitle" format
    title = f"{emoji} {name} for {benefit} #Shorts"
    if len(title) > 100:
        title = title[:97] + "…"

    # Category-specific hashtags + variant tags + universal viral
    cat_tags = _CATEGORY_HASHTAGS.get(category_id, "")
    variant_hashtags = " ".join(f"#{t.replace(' ', '')}" for t in tags_base[:15])
    hashtags = f"{_UNIVERSAL_HASHTAGS}\n{cat_tags}\n{variant_hashtags}"

    description = (
        f"{emoji} {name}\n"
        f"{hook_line}\n\n"
        f"🔊 Turn on sound for the full experience!\n"
        f"🌿 Subscribe for daily relaxation sounds 🔔\n"
        f"🆕 4 new videos every day!\n\n"
        f"Perfect for: sleep, study, meditation, yoga, focus, stress relief & relaxation.\n\n"
        f"---\n"
        f"{hashtags}"
    )

    youtube = get_youtube_client()
    _verify_channel(youtube)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": all_tags[:30],
            "categoryId": "10",    # Music — better targeting for ambient/relaxation
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=256 * 1024,
    )

    logger.info(f"Uploading: {video_path.name}")
    logger.info(f"Title: {title}")

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
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")

            video_id = response["id"]
            logger.info(f"Upload complete! https://www.youtube.com/watch?v={video_id}")
            _record_upload(video_id, title, variant)

            # ── Post-upload actions (non-fatal if they fail) ──────────────
            _auto_like(youtube, video_id)
            _post_comment(youtube, video_id, category_id)
            add_video_to_category_playlist(youtube, video_id, category_id)

            return video_id

        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"HTTP {e.resp.status} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def upload_compilation(video_path: Path, month_str: str, youtube=None) -> str:
    """Upload a monthly Best Of compilation. Returns video_id."""
    if not video_path.exists():
        raise FileNotFoundError(f"Compilation video not found: {video_path}")

    if youtube is None:
        youtube = get_youtube_client()

    title = f"Best of {month_str} \U0001f33f | Relax Sound Compilation"
    if len(title) > 100:
        title = title[:97] + "\u2026"

    description = (
        f"\U0001f3b5 Best of {month_str} \u2014 top relaxing sounds of the month!\n\n"
        "Our most-watched relaxation videos in one place:\n"
        "\U0001f327 Rain sounds \u2022 \U0001f9d8 Meditation tones \u2022 \U0001f30a Ocean waves\n"
        "\U0001f333 Forest ambience \u2022 \U0001f525 Fireplace crackling \u2022 \U0001f634 Deep sleep sounds\n\n"
        "#relaxingsounds #sleepsounds #ASMR #meditation #relaxation #compilation\n\n"
        "\U0001f514 Subscribe for daily relaxation sounds.\n"
        "\U0001f50a Turn on sound for the full experience!"
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["best of", "compilation", "relaxing sounds", "sleep sounds",
                     "ASMR", "meditation", "ambient", month_str.lower()],
            "categoryId": "22",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path), mimetype="video/mp4", resumable=True, chunksize=256 * 1024
    )

    logger.info(f"Uploading compilation: {title}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Compilation upload: {int(status.progress() * 100)}%")

    video_id = response["id"]
    logger.info(f"Compilation uploaded: https://www.youtube.com/watch?v={video_id}")
    return video_id


def _record_upload(video_id: str, title: str, variant: dict) -> None:
    f = config.UPLOADED_FILE
    data: dict = {"uploads": []}
    if f.exists():
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)

    data["uploads"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "category_id": variant.get("category_id", ""),
        "variant_id": variant.get("id", ""),
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    })

    with open(f, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
    logger.info(f"Recorded in {f}")
