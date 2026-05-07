"""assemble.py — Build a relaxation Short with rich overlay.

Visual design:
  • Hook text for first 3s   — grabs the 2-second algorithm retention check
  • Category-coloured accent  — visual brand identity per sound type
  • Fake bottom gradient      — readability without covering the scenery
  • Animated progress bar     — keeps viewers watching to the end
  • Loop badge                — sets expectation, reduces drop-off
  • Category label badge      — top-right pill for instant visual ID
  • End-screen CTA (last 5s)  — "Follow + Save" drives algorithm signals
  • Slot-based hook rotation  — 3 hooks/category so each post feels fresh
  • Black screen fade         — fades to black at 5s for sleep-friendly viewing
"""
import logging
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

WIDTH  = 1080
HEIGHT = 1920

# ── Per-category accent colours (ffmpeg 0xRRGGBB) ────────────────────────────
CAT_COLORS = {
    "rain":        "0x2255BB",   # deep blue
    "forest":      "0x1A7A22",   # forest green
    "ocean":       "0x006688",   # teal
    "fireplace":   "0xBB4400",   # ember orange
    "meditation":  "0x6633AA",   # purple
    "deep_sleep":  "0x1A1A66",   # midnight blue
    "white_noise": "0x445566",   # slate
    "coffee_shop": "0x6B3A2A",   # coffee brown
}
_CAT_COLOR_DEFAULT = "0x222233"

# ── Per-category color grading (ffmpeg eq filter) ─────────────────────────────
# eq params: saturation, gamma_r/g/b (>1 boosts, <1 reduces), gamma (overall)
CAT_GRADE = {
    "rain":        "eq=saturation=0.90:gamma_r=0.93:gamma_b=1.08",    # cool, muted blue
    "forest":      "eq=saturation=1.15:gamma_r=1.05:gamma_g=1.03",    # warm, lush green
    "ocean":       "eq=saturation=0.95:gamma_r=0.91:gamma_b=1.10",    # cool teal
    "fireplace":   "eq=saturation=1.20:gamma_r=1.12:gamma_b=0.88",    # warm amber/orange
    "meditation":  "eq=saturation=0.82:gamma=1.06:gamma_b=1.05",      # soft, dreamy purple
    "deep_sleep":  "eq=saturation=0.78:gamma=0.93:gamma_b=1.06",      # dark, cool, calm
    "white_noise": "eq=saturation=0.88:gamma=1.02",                   # neutral, clean
    "coffee_shop": "eq=saturation=1.10:gamma_r=1.10:gamma_b=0.92",    # warm golden-brown
}
_GRADE_DEFAULT = "eq=saturation=1.0"

# ── Per-category hook lines (shown for first 3 s) ─────────────────────────────
# 3 hooks per category — rotated by slot so each daily post feels fresh.
# Questions > statements — viewer thinks "that's me" → keeps watching.
CAT_HOOKS: dict[str, list[str]] = {
    "rain":        ["Can't sleep?",          "Stressed out?",           "Rain to the rescue..."],
    "forest":      ["Feeling stressed?",     "Take a deep breath...",   "Nature heals"],
    "ocean":       ["Need to relax?",        "Clear your mind...",      "Drift away..."],
    "fireplace":   ["Get cozy...",           "Time to unwind...",       "Warm your soul"],
    "meditation":  ["Need to focus?",        "Quiet your mind...",      "Find your peace"],
    "deep_sleep":  ["Can't sleep?",          "Silence the noise...",    "Rest deeply..."],
    "white_noise": ["Stay focused",          "Block the noise",         "Deep focus mode"],
    "coffee_shop": ["Get in the zone...",    "Study time!",             "Focus and flow"],
}
_HOOK_DEFAULT = "Need to relax?"

# Fade to black timing constants
_FADE_START  = 5   # seconds — nature footage visible before fade begins
_FADE_DUR    = 3   # seconds — fade duration (black screen complete at _FADE_START + _FADE_DUR)
_BLACK_START = _FADE_START + _FADE_DUR  # = 8s — when black screen is fully active


def _detect_font() -> str:
    """Return ffmpeg-escaped font path for current OS."""
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


FONT_PATH = _detect_font()


def esc(s: str) -> str:
    """Escape text for ffmpeg drawtext."""
    return (s.replace("\\", "\\\\")
             .replace("'",  "’")   # curly apostrophe — safe in filter
             .replace('"',  "“")
             .replace(":",  "\\:")
             .replace("[",  "\\[")
             .replace("]",  "\\]")
             .replace(",",  " ")
             .replace(";",  " ")
             .replace("%",  "%%")
             .replace("$",  "\\$")
             .replace("\n", " "))


def _run_ffmpeg(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run ffmpeg cross-platform."""
    if platform.system() == "Windows":
        bat = cwd / "_ffmpeg_run.bat"
        cmd_line = " ".join(
            f'"{ a}"' if (" " in a and not a.startswith('"')) else a
            for a in args
        )
        bat.write_text(f'@echo off\ncd /d "{cwd}"\n{cmd_line}\n', encoding="utf-8")
        result = subprocess.run([str(bat)], capture_output=True, text=True, shell=True)
        bat.unlink(missing_ok=True)
    else:
        result = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return result


def _video_has_audio(video_path: Path) -> bool:
    """Return True if video has a real, non-silent audio stream."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        if "audio" not in r.stdout:
            return False
        r2 = subprocess.run(
            ["ffmpeg", "-i", str(video_path),
             "-t", "10", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        for line in r2.stderr.splitlines():
            if "mean_volume" in line:
                try:
                    db = float(line.split(":")[1].strip().replace(" dB", ""))
                    if db < -90.0:
                        logger.info(f"Audio silent ({db:.1f}dB) — using fallback")
                        return False
                    return True
                except Exception:
                    pass
        return True
    except Exception:
        return False


def _build_vf(theme: dict, duration: int, slot: int = 0) -> str:
    """
    Build the full ffmpeg -vf filter chain.

    Layout (1080x1920):
      0-5s    : nature footage visible (hook text in top banner)
      5-8s    : smooth fade to black
      8s+     : black screen with centered name/subtitle + bottom badge

      y=0-90    : HOOK TEXT (0-3s) — same banner zone
      y=90-1480 : clean ambient video (no overlays)
      y=0-56    : category label badge, top-right pill (after hook fades)
      y=1480-1920: bottom zone
          gradient, accent stripe, name, subtitle, loop badge (0-8s)
      centered  : name + subtitle on black screen (8s+)
    """
    font  = FONT_PATH
    cat   = theme.get("category_id", "")
    color = CAT_COLORS.get(cat, _CAT_COLOR_DEFAULT)
    grade = CAT_GRADE.get(cat, _GRADE_DEFAULT)

    # Slot-based hook rotation
    hooks_opt = CAT_HOOKS.get(cat)
    if isinstance(hooks_opt, list):
        hook_raw = hooks_opt[slot % len(hooks_opt)]
    elif isinstance(hooks_opt, str):
        hook_raw = hooks_opt
    else:
        hook_raw = _HOOK_DEFAULT
    hook = esc(theme.get("hook", hook_raw))

    name  = esc(theme["name"].upper())
    sub   = esc(theme["subtitle"])

    # Category label badge text (ASCII only — emoji unsupported in drawtext)
    cat_label = cat.upper().replace("_", " ")

    # Dynamic loop label
    if duration >= 60 and duration % 60 == 0:
        loop_label = f"{duration // 60} MIN LOOP"
    elif duration >= 60:
        loop_label = f"{duration // 60}:{duration % 60:02d} LOOP"
    else:
        loop_label = f"{duration}S LOOP"

    bs = _BLACK_START  # shorthand: 8

    filters = [
        # ── Canvas ──────────────────────────────────────────────────────────
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={WIDTH}:{HEIGHT}",
        "setsar=1",

        # ── Color grading — per-category mood ───────────────────────────────
        grade,

        # ── Vignette — subtle dark edge, pulls focus to centre ───────────────
        "vignette=angle=PI/5:mode=forward",

        # ── Sharpening — luma 0.8, chroma 0.4 (crisp on mobile screens) ─────
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.8"
        ":chroma_msize_x=3:chroma_msize_y=3:chroma_amount=0.4",

        # ── Fade to black — starts at 5s, complete at 8s ────────────────────
        # After t=8s the output stays black; text overlays are drawn on top.
        f"fade=t=out:st={_FADE_START}:d={_FADE_DUR}",

        # ── Hook banner (0–3 s) ──────────────────────────────────────────────
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.90:t=fill"
        f":enable='between(t,0,2.5)'",
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.40:t=fill"
        f":enable='between(t,2.5,2.8)'",
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.10:t=fill"
        f":enable='between(t,2.8,3.0)'",
        # Thin bottom accent on hook box
        f"drawbox=x=0:y=188:w={WIDTH}:h=7:color={color}:t=fill"
        f":enable='between(t,0,2.5)'",
        # Hook text — 3-step alpha fade
        f"drawtext=fontfile='{font}':text='{hook}'"
        f":fontsize=74:fontcolor=white:x=(w-text_w)/2:y=62"
        f":borderw=3:bordercolor=black@0.55"
        f":enable='between(t,0,2.5)'",
        f"drawtext=fontfile='{font}':text='{hook}'"
        f":fontsize=74:fontcolor=white@0.45:x=(w-text_w)/2:y=62"
        f":borderw=2:bordercolor=black@0.20"
        f":enable='between(t,2.5,2.8)'",
        f"drawtext=fontfile='{font}':text='{hook}'"
        f":fontsize=74:fontcolor=white@0.10:x=(w-text_w)/2:y=62"
        f":borderw=0:bordercolor=black@0.00"
        f":enable='between(t,2.8,3.0)'",

        # ── Bottom gradient (visible during nature footage, 0-8s) ─────────
        f"drawbox=x=0:y=1480:w={WIDTH}:h=440:color=black@0.28:t=fill"
        f":enable='lt(t,{bs})'",
        f"drawbox=x=0:y=1610:w={WIDTH}:h=310:color=black@0.52:t=fill"
        f":enable='lt(t,{bs})'",
        f"drawbox=x=0:y=1740:w={WIDTH}:h=180:color=black@0.78:t=fill"
        f":enable='lt(t,{bs})'",

        # ── Left category accent stripe (nature phase only) ──────────────────
        f"drawbox=x=0:y=1480:w=10:h=440:color={color}:t=fill"
        f":enable='lt(t,{bs})'",

        # ── Sound name (bottom, nature phase) ───────────────────────────────
        f"drawtext=fontfile='{font}':text='{name}'"
        f":fontsize=84:fontcolor=white:x=(w-text_w)/2:y=1555"
        f":borderw=3:bordercolor={color}@0.40"
        f":enable='lt(t,{bs})'",

        # ── Thin separator line ──────────────────────────────────────────────
        f"drawbox=x=80:y=1652:w={WIDTH - 160}:h=1:color={color}@0.50:t=fill"
        f":enable='lt(t,{bs})'",

        # ── Subtitle (bottom, nature phase) ─────────────────────────────────
        f"drawtext=fontfile='{font}':text='{sub}'"
        f":fontsize=42:fontcolor=white@0.93:x=(w-text_w)/2:y=1668"
        f":borderw=2:bordercolor=black@0.70"
        f":enable='lt(t,{bs})'",

        # ── Loop badge (nature phase) ──────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{loop_label}'"
        f":fontsize=28:fontcolor=white@0.55:x=(w-text_w)/2:y=1873"
        f":enable='lt(t,{bs})'",

        # ── Watermark — bottom-right, very subtle ─────────────────────────────
        f"drawtext=fontfile='{font}':text='Relax Sound'"
        f":fontsize=22:fontcolor=white@0.30:x=w-text_w-18:y=h-36"
        f":borderw=1:bordercolor=black@0.15",

        # ── Category label badge — top-right pill (visible after hook fades) ──
        f"drawbox=x={WIDTH - 210}:y=8:w=202:h=50:color=black@0.62:t=fill"
        f":enable='between(t,3.1,{duration})'",
        f"drawtext=fontfile='{font}':text='{cat_label}'"
        f":fontsize=25:fontcolor={color}@0.95"
        f":x=w-text_w-18:y=21"
        f":borderw=1:bordercolor=black@0.35"
        f":enable='between(t,3.1,{duration})'",

        # ── Black screen: centered name (appears after fade completes) ────────
        f"drawtext=fontfile='{font}':text='{name}'"
        f":fontsize=80:fontcolor=white@0.90:x=(w-text_w)/2:y=(h-text_h)/2-80"
        f":borderw=2:bordercolor=black@0.20"
        f":enable='gte(t,{bs})'",

        # ── Black screen: centered subtitle ──────────────────────────────────
        f"drawtext=fontfile='{font}':text='{sub}'"
        f":fontsize=44:fontcolor=white@0.70:x=(w-text_w)/2:y=(h-text_h)/2+10"
        f":borderw=1:bordercolor=black@0.15"
        f":enable='gte(t,{bs})'",

        # ── Black screen: small 'BLACK SCREEN' badge at bottom ────────────────
        f"drawtext=fontfile='{font}':text='BLACK SCREEN'"
        f":fontsize=24:fontcolor=white@0.30:x=(w-text_w)/2:y=h-60"
        f":enable='gte(t,{bs})'",
    ]

    return ",".join(filters)


def _seamless_audio_filter(src_label: str, duration: int, cf: int = 3,
                            volume: float = 2.5, has_aloop: bool = False) -> str:
    """Return a filter_complex fragment that produces exactly `duration` seconds
    of seamlessly-looping audio from `src_label`.

    Strategy — crossfade at the loop boundary:
      1. Pull duration+cf seconds from the (infinite) source.
      2. Split into two streams:
           a_main  = first `duration` seconds (the full playback)
           a_start = seconds [duration .. duration+cf]  which, because the
                     source loops, equals the FIRST cf seconds of the clip.
      3. acrossfade(d=cf): fades the last cf seconds of a_main into the first
         cf seconds of a_start.
      Output = duration + cf - cf = duration seconds. ✓
      At t=duration the audio has fully transitioned to "beginning of clip",
      so when YouTube replays from t=0 the listener hears no jump.

    Args:
        src_label:  ffmpeg pad label, e.g. "[1:a]"
        duration:   desired output duration in seconds
        cf:         crossfade duration in seconds (default 3)
        volume:     volume multiplier (default 2.5; pass 1.0 for lavfi sources)
        has_aloop:  if True, prepend aloop filter (needed when src is a finite
                    video audio stream — not needed for stream_loop/-1 inputs)
    """
    aloop_prefix = "aloop=loop=-1:size=2e+09," if has_aloop else ""
    vol_filter   = f"volume={volume}," if volume != 1.0 else ""
    return (
        f"{src_label}"
        f"{aloop_prefix}"
        f"atrim=duration={duration + cf},"
        f"asetpts=PTS-STARTPTS,"
        f"{vol_filter}"
        f"asplit=2[_a1][_a2];"
        f"[_a1]atrim=0:{duration},asetpts=PTS-STARTPTS[_amain];"
        f"[_a2]atrim={duration}:{duration + cf},asetpts=PTS-STARTPTS[_astart];"
        f"[_amain][_astart]acrossfade=d={cf}:c1=tri:c2=tri[aout]"
    )


def build_video(theme: dict, media_path: Path, output_path: Path,
                duration: int = 60, audio_path: Path | None = None,
                slot: int = 0, crossfade_dur: int = 3) -> Path:
    """
    Build a relaxation Short video with seamless audio loop.

    Audio priority:
      1. audio_path file provided → loop that file (real birds/rain/etc.)
      2. video with non-silent audio → use original video audio
      3. video without audio / image → lavfi synthetic fallback

    The audio crossfades at the loop boundary so the end blends imperceptibly
    into the beginning — no fade-out, no fade-in, no audible seam.

    Args:
        theme:         Variant dict (name, subtitle, category_id, audio_lavfi, …)
        media_path:    Source video (.mp4) or image (.jpg/.png)
        output_path:   Destination .mp4
        duration:      Output duration in seconds
        audio_path:    Optional real audio file to loop
        slot:          Daily slot index (0-3) used to rotate hook text per post
        crossfade_dur: Seconds of crossfade at the loop boundary (default 3)
    """
    CF = crossfade_dur

    vf        = _build_vf(theme, duration, slot)
    is_video  = media_path.suffix.lower() == ".mp4"
    media_str = str(media_path.resolve()).replace("\\", "/")
    out_str   = str(output_path.resolve()).replace("\\", "/")

    # Lavfi fallback (used only when no real audio is available)
    audio_lavfi = theme.get("audio_lavfi", "anoisesrc=color=brown,volume=4.0")

    encode = [
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ]

    if audio_path and audio_path.exists():
        # ── Case 1: real audio file (birds, rain, fire…) ─────────────────────
        audio_str = str(audio_path.resolve()).replace("\\", "/")
        logger.info(f"Using real audio: {audio_path.name}")
        input_args = (
            ["-stream_loop", "-1", "-i", media_str] if is_video
            else ["-loop", "1", "-i", media_str]
        )
        audio_flt = _seamless_audio_filter("[1:a]", duration, CF, volume=2.5)
        ffmpeg_args = [
            "ffmpeg", "-y",
            *input_args,
            "-stream_loop", "-1", "-i", audio_str,
            "-filter_complex",
            f"[0:v]{vf}[vout];{audio_flt}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            *encode,
            out_str,
        ]

    elif is_video and _video_has_audio(media_path):
        # ── Case 2: video has usable original audio ───────────────────────────
        logger.info("Using video's own audio")
        audio_flt = _seamless_audio_filter("[0:a]", duration, CF, volume=2.5)
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-filter_complex",
            f"[0:v]{vf}[vout];{audio_flt}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            *encode,
            out_str,
        ]

    elif is_video:
        # ── Case 3: video but mute → lavfi ───────────────────────────────────
        logger.info("Video mute — lavfi fallback")
        audio_flt = _seamless_audio_filter("[1:a]", duration, CF, volume=1.0)
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-filter_complex",
            f"[0:v]{vf}[vout];{audio_flt}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            *encode,
            out_str,
        ]

    else:
        # ── Case 4: still image + lavfi ──────────────────────────────────────
        logger.info("Image + lavfi fallback")
        audio_flt = _seamless_audio_filter("[1:a]", duration, CF, volume=1.0)
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-filter_complex",
            f"[0:v]{vf}[vout];{audio_flt}",
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration),
            *encode,
            "-shortest",
            out_str,
        ]

    logger.info(f"Building: {theme['name']} ({duration}s)")
    result = _run_ffmpeg(ffmpeg_args, output_path.parent)

    if result.returncode != 0:
        logger.error(f"ffmpeg error:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"Video build failed: {theme['name']}")

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"Done: {output_path.name} ({size_mb:.1f} MB)")
    return output_path
