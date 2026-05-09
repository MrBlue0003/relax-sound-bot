"""assemble_long.py — Build 11-hour landscape ambient videos for Relax Sound.

Structure of every video:
  [0:00 – 0:08]       Whisk intro  — branded title card (nicely edited)
  [0:08 – 4:00:08]    Content      — looping ambient video + audio (4 hours)
  [4:00:08 – 11:00:08] Black screen — audio continues, screen dark for sleep

Encoding:
  • 1280×720, 5 fps (ambient — no detail lost at low fps)
  • ultrafast / CRF 28 (fast encode, small file, fine for ambient)
  • Black segment compresses to near-zero bytes in H.264
"""

import logging
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Output canvas ─────────────────────────────────────────────────────────────
OUT_W   = 1280
OUT_H   = 720
OUT_FPS = 5          # 5 fps — sufficient for ambient; greatly speeds up encode

# ── Duration constants ────────────────────────────────────────────────────────
INTRO_DURATION   = 8           # seconds — Whisk intro clip length
CONTENT_DURATION = 4 * 3600   # 4 hours of visible ambient content
BLACK_DURATION   = 7 * 3600   # 7 hours of black screen
TOTAL_DURATION   = INTRO_DURATION + CONTENT_DURATION + BLACK_DURATION  # 39 608 s

# ── Encoding ──────────────────────────────────────────────────────────────────
VIDEO_PRESET  = "ultrafast"
VIDEO_CRF     = 28
AUDIO_BITRATE = "128k"
AUDIO_VOLUME  = 2.5

# ── Accent colours per category (same palette as shorts) ─────────────────────
CAT_COLORS = {
    "rain":        "0x2255BB",
    "forest":      "0x1A7A22",
    "ocean":       "0x006688",
    "fireplace":   "0xBB4400",
    "meditation":  "0x6633AA",
    "deep_sleep":  "0x1A1A66",
    "white_noise": "0x445566",
    "coffee_shop": "0x6B3A2A",
}
_COLOR_DEFAULT = "0x223355"


def _detect_font() -> str:
    if platform.system() == "Windows":
        return "C\\:/Windows/Fonts/arialbd.ttf"
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return candidates[0]


def _esc(s: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return (s.replace("\\", "\\\\")
             .replace("'",  "’")
             .replace('"',  "“")
             .replace(":",  "\\:")
             .replace("[",  "\\[")
             .replace("]",  "\\]")
             .replace(",",  " ")
             .replace(";",  " ")
             .replace("%",  "%%")
             .replace("\n", " "))


def _probe_audio_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe. Returns 0 on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _make_seamless_loop(audio_path: Path, work_dir: Path, xfade: float = 2.0) -> Path:
    """Pre-bake a seamlessly-looping version of a short audio file.

    For files shorter than 180 s, the loop point is a hard cut that becomes
    audible after many repetitions.  This function creates a same-duration
    output whose *end* crossfades into its *beginning*, so that stream_loop -1
    plays it without any click at the splice point.

    Strategy
    --------
    Split the source into three slices:
      body  = [0, dur-xfade)          → plays normally
      tail  = [dur-xfade, dur)        → end of file
      head  = [0, xfade)              → beginning of file
    Crossfade tail→head to create a smooth transition region, then concat:
      baked = body + crossfade(tail, head)
    Duration stays ≈ dur.  When -stream_loop replays the baked file, the
    last sample fades toward the beginning, matching iteration N+1's start.
    """
    dur = _probe_audio_duration(audio_path)
    if dur <= 0 or dur >= 180:
        return audio_path

    xfade = min(xfade, dur * 0.12)
    out = work_dir / f"loop_seamless_{audio_path.stem}.mp3"

    fc = (
        f"[0:a]asplit=3[a1][a2][a3];"
        f"[a1]atrim=0:{dur - xfade:.3f},asetpts=PTS-STARTPTS[body];"
        f"[a2]atrim={dur - xfade:.3f}:{dur:.3f},asetpts=PTS-STARTPTS[tail];"
        f"[a3]atrim=0:{xfade:.3f},asetpts=PTS-STARTPTS[head];"
        f"[tail][head]acrossfade=d={xfade:.3f}:c1=tri:c2=tri[xf];"
        f"[body][xf]concat=n=2:v=0:a=1[aout]"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-filter_complex", fc,
        "-map", "[aout]",
        "-codec:a", "libmp3lame", "-q:a", "2",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not out.exists():
        logger.warning(f"Seamless loop prep failed — using original: {audio_path.name}")
        return audio_path
    logger.info(f"Seamless loop baked: {out.name} ({dur:.1f}s, xfade={xfade:.1f}s)")
    return out


def _is_video(p: Path) -> bool:
    return p.suffix.lower() in (".mp4", ".mov", ".avi", ".webm", ".mkv")


def _video_has_audio(p: Path) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(p)],
            capture_output=True, text=True, timeout=15,
        )
        if "audio" not in r.stdout:
            return False
        r2 = subprocess.run(
            ["ffmpeg", "-i", str(p), "-t", "10",
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        for line in r2.stderr.splitlines():
            if "mean_volume" in line:
                db = float(line.split(":")[1].strip().replace(" dB", ""))
                return db > -90.0
        return True
    except Exception:
        return False


def _intro_vf(title: str, category: str) -> str:
    """Build ffmpeg -vf chain for the Whisk intro clip.

    Layout (1280×720):
      • Whisk video dimmed with dark overlay
      • Large sound name centred
      • Duration tag below name (accent colour)
      • Thin accent line above and below the title block
      • Channel branding bottom-centre
      • Fade-in from black (0→1.5 s), fade-out to black (6.5→8 s)
    """
    font    = _detect_font()
    color   = CAT_COLORS.get(category, _COLOR_DEFAULT)
    t_esc   = _esc(title.upper())
    dur_tag = _esc("11 HOURS  •  RELAX & SLEEP")
    brand   = _esc("Relax Sound")
    fade_in = 1.5
    fade_out_start = INTRO_DURATION - 1.5

    return ",".join([
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase",
        f"crop={OUT_W}:{OUT_H}",
        "setsar=1",
        f"fps=fps={OUT_FPS}",

        # Dark overlay — makes text pop against any background
        "drawbox=x=0:y=0:w=1280:h=720:color=black@0.62:t=fill",

        # Thin accent bar above title block
        f"drawbox=x=80:y=270:w=1120:h=3:color={color}:t=fill",

        # Main title — sound name
        f"drawtext=fontfile='{font}':text='{t_esc}'"
        f":fontsize=88:fontcolor=white"
        f":x=(w-text_w)/2:y=290"
        f":borderw=4:bordercolor=black@0.55",

        # Duration tag — accent colour
        f"drawtext=fontfile='{font}':text='{dur_tag}'"
        f":fontsize=38:fontcolor={color}@0.95"
        f":x=(w-text_w)/2:y=400"
        f":borderw=2:bordercolor=black@0.40",

        # Thin accent bar below title block
        f"drawbox=x=80:y=450:w=1120:h=3:color={color}:t=fill",

        # Channel branding bottom
        f"drawtext=fontfile='{font}':text='{brand}'"
        f":fontsize=28:fontcolor=white@0.55"
        f":x=(w-text_w)/2:y=h-48"
        f":borderw=1:bordercolor=black@0.20",

        # Fade in / out
        f"fade=t=in:st=0:d={fade_in}:color=black",
        f"fade=t=out:st={fade_out_start}:d={fade_in}:color=black",
    ])


def build_long_video(
    media_path: Path,
    audio_path: Path | None,
    output_path: Path,
    duration: int = TOTAL_DURATION,   # kept for backward-compat (ignored)
    title: str = "",
    category: str = "",
) -> Path:
    """
    Build an 11-hour ambient video:
      intro (8 s)  +  content (4 h)  +  black screen (7 h)

    Args:
        media_path:   Ambient source video or image to loop for 4 h.
        audio_path:   Real audio file to loop for full 11 h. If None,
                      uses video audio or lavfi brown-noise.
        output_path:  Destination MP4.
        duration:     Ignored (kept for backward-compat). Always 11 h.
        title:        Sound name shown on the intro card.
        category:     Category id for accent colour (e.g. "rain").
    """
    is_vid    = _is_video(media_path)
    media_str = str(media_path.resolve()).replace("\\", "/")
    out_str   = str(output_path.resolve()).replace("\\", "/")

    # Locate the Whisk intro
    intro_path = Path(__file__).parent.parent / "assets" / "whisk_intro.mp4"
    if not intro_path.exists():
        logger.warning("whisk_intro.mp4 not found in assets — skipping intro")
        intro_path = None

    intro_str = str(intro_path.resolve()).replace("\\", "/") if intro_path else None

    # ── Build filter_complex ──────────────────────────────────────────────────
    #
    # Input indices depend on whether we have intro + audio:
    #   [0] = whisk intro (if exists)
    #   [0 or 1] = ambient media (stream_loop -1)
    #   [last] = audio (stream_loop -1, only for Cases 1 & 2)
    #
    # We assemble the command in parts to keep it readable.

    has_intro      = intro_path is not None
    intro_vf_str   = _intro_vf(title, category) if has_intro else ""

    # Ambient content filter (looped input → trim to CONTENT_DURATION)
    content_vf = (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},"
        f"setsar=1,"
        f"fps=fps={OUT_FPS},"
        f"trim=duration={CONTENT_DURATION},"
        f"setpts=PTS-STARTPTS"
    )

    # Black screen: generated by lavfi, 1 fps to minimise encode time
    black_seg = (
        f"color=c=black:s={OUT_W}x{OUT_H}:r=1:d={BLACK_DURATION}[black_v]"
    )

    # ── Determine audio source ────────────────────────────────────────────────
    def _audio_filter(label: str, needs_aloop: bool) -> str:
        """Seamless-loop audio filter for the full TOTAL_DURATION."""
        aloop = "aloop=loop=-1:size=2e+09," if needs_aloop else ""
        return (
            f"{label}"
            f"{aloop}"
            f"atrim=duration={TOTAL_DURATION},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={AUDIO_VOLUME},"
            f"afade=t=in:st=0:d=5"
            f"[aout]"
        )

    base_encode = [
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    # ── Case 1: explicit real audio file ─────────────────────────────────────
    if audio_path and audio_path.exists():
        audio_path = _make_seamless_loop(audio_path, output_path.parent)
        audio_str = str(audio_path.resolve()).replace("\\", "/")
        logger.info(f"Audio: {audio_path.name} (looped for {TOTAL_DURATION}s)")

        # Inputs
        inputs = []
        if has_intro:
            inputs += ["-i", intro_str]                          # [0] intro
        if is_vid:
            inputs += ["-stream_loop", "-1", "-i", media_str]   # [1] video
        else:
            inputs += ["-loop", "1", "-i", media_str]            # [1] image
        inputs += ["-stream_loop", "-1", "-i", audio_str]        # [2] audio

        # Label indices
        intro_lbl   = "[0:v]" if has_intro else None
        media_lbl   = f"[{'1' if has_intro else '0'}:v]"
        audio_lbl   = f"[{'2' if has_intro else '1'}:a]"

        # Build filter_complex
        fc_parts = []
        if has_intro:
            fc_parts.append(f"{intro_lbl}{intro_vf_str}[intro_v]")
        fc_parts.append(f"{media_lbl}{content_vf}[content_v]")
        fc_parts.append(black_seg)

        if has_intro:
            fc_parts.append("[intro_v][content_v][black_v]concat=n=3:v=1:a=0[vout]")
        else:
            fc_parts.append("[content_v][black_v]concat=n=2:v=1:a=0[vout]")

        fc_parts.append(_audio_filter(audio_lbl, needs_aloop=False))
        fc = ";".join(fc_parts)

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", fc,
               "-map", "[vout]", "-map", "[aout]"]
            + base_encode
            + ["-t", str(TOTAL_DURATION), out_str]
        )

    # ── Case 2: video with its own audio ─────────────────────────────────────
    elif is_vid and _video_has_audio(media_path):
        logger.info("Using video's own audio (looped for full duration)")

        inputs = []
        if has_intro:
            inputs += ["-i", intro_str]
        inputs += ["-stream_loop", "-1", "-i", media_str]

        intro_lbl = "[0:v]" if has_intro else None
        media_v   = f"[{'1' if has_intro else '0'}:v]"
        media_a   = f"[{'1' if has_intro else '0'}:a]"

        fc_parts = []
        if has_intro:
            fc_parts.append(f"{intro_lbl}{intro_vf_str}[intro_v]")
        fc_parts.append(f"{media_v}{content_vf}[content_v]")
        fc_parts.append(black_seg)
        if has_intro:
            fc_parts.append("[intro_v][content_v][black_v]concat=n=3:v=1:a=0[vout]")
        else:
            fc_parts.append("[content_v][black_v]concat=n=2:v=1:a=0[vout]")
        fc_parts.append(_audio_filter(media_a, needs_aloop=True))
        fc = ";".join(fc_parts)

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", fc,
               "-map", "[vout]", "-map", "[aout]"]
            + base_encode
            + ["-t", str(TOTAL_DURATION), out_str]
        )

    # ── Case 3 & 4: no real audio → lavfi brown-noise ─────────────────────────
    else:
        if is_vid:
            logger.warning("Video mute — lavfi brown-noise fallback")
        else:
            logger.warning("Image — lavfi brown-noise fallback")

        # Generate brown noise for full duration
        noise_src = (
            f"anoisesrc=c=brown:a=0.15:r=44100,"
            f"volume={AUDIO_VOLUME},"
            f"afade=t=in:st=0:d=5,"
            f"atrim=duration={TOTAL_DURATION}"
        )

        inputs = []
        if has_intro:
            inputs += ["-i", intro_str]
        if is_vid:
            inputs += ["-stream_loop", "-1", "-i", media_str]
        else:
            inputs += ["-loop", "1", "-i", media_str]
        inputs += ["-f", "lavfi", "-i", noise_src]

        intro_lbl = "[0:v]" if has_intro else None
        media_lbl = f"[{'1' if has_intro else '0'}:v]"
        audio_lbl = f"[{'2' if has_intro else '1'}:a]"

        fc_parts = []
        if has_intro:
            fc_parts.append(f"{intro_lbl}{intro_vf_str}[intro_v]")
        fc_parts.append(f"{media_lbl}{content_vf}[content_v]")
        fc_parts.append(black_seg)
        if has_intro:
            fc_parts.append("[intro_v][content_v][black_v]concat=n=3:v=1:a=0[vout]")
        else:
            fc_parts.append("[content_v][black_v]concat=n=2:v=1:a=0[vout]")
        fc_parts.append(f"{audio_lbl}acopy[aout]")
        fc = ";".join(fc_parts)

        extra = ["-tune", "stillimage"] if not is_vid else []
        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", fc,
               "-map", "[vout]", "-map", "[aout]"]
            + base_encode
            + extra
            + ["-t", str(TOTAL_DURATION), out_str]
        )

    logger.info(
        f"Encoding 11h video: intro({INTRO_DURATION}s) + "
        f"content({CONTENT_DURATION//3600}h) + black({BLACK_DURATION//3600}h)"
    )
    logger.info(f"ffmpeg: {' '.join(cmd[:10])} ...")

    timeout_s = max(TOTAL_DURATION * 3, 7200)   # at least 2h headroom
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

    if result.returncode != 0:
        logger.error(f"ffmpeg stderr (last 4000):\n{result.stderr[-4000:]}")
        raise RuntimeError(f"ffmpeg failed building long video: {output_path.name}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Long video ready: {output_path.name} ({size_mb:.1f} MB)")
    return output_path
