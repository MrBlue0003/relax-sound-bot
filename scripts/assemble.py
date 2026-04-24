"""assemble.py — Build a 120-second relaxation Short with rich overlay.

Visual design:
  • Hook text for first 3s  — grabs the 2-second algorithm retention check
  • Category-coloured accent — visual brand identity per sound type
  • Fake bottom gradient    — readability without covering the scenery
  • Animated progress bar   — keeps viewers watching to the end
  • Loop badge              — sets expectation, reduces drop-off
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
    "rain":       "0x2255BB",   # deep blue
    "forest":     "0x1A7A22",   # forest green
    "ocean":      "0x006688",   # teal
    "fireplace":  "0xBB4400",   # ember orange
    "meditation": "0x6633AA",   # purple
    "deep_sleep": "0x1A1A66",   # midnight blue
    "white_noise":"0x445566",   # slate
}
_CAT_COLOR_DEFAULT = "0x222233"

# ── Per-category hook lines (shown for first 3 s) ─────────────────────────────
# Questions > statements — viewer thinks "that's me" → keeps watching
CAT_HOOKS = {
    "rain":       "Can't sleep?",
    "forest":     "Feeling stressed?",
    "ocean":      "Need to relax?",
    "fireplace":  "Get cozy...",
    "meditation": "Need to focus?",
    "deep_sleep": "Can't sleep?",
    "white_noise":"Stay focused",
}
_HOOK_DEFAULT = "Need to relax?"


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
             .replace("'",  "\u2019")   # curly apostrophe — safe in filter
             .replace('"',  "\u201c")
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
            f'"{a}"' if (" " in a and not a.startswith('"')) else a
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


def _build_vf(theme: dict, duration: int) -> str:
    """
    Build the full ffmpeg -vf filter chain.

    Layout (1080×1920):
      y=0–180   : HOOK TEXT — category colour box, big text, 3 s then gone
      y=180–1500: clean ambient video (no overlays)
      y=1500–1920: bottom zone
          1500–1920: fake gradient (3 dark layers)
          1500–1920: 10-px left accent stripe
          1560     : NAME   (fontsize 84, white, bold)
          1700     : subtitle (fontsize 42, white 92%)
          1860–1868: progress bar track (dark)
          1860–1868: progress bar fill (animated, category colour)
          1876     : "LOOP" badge text
    """
    font  = FONT_PATH
    cat   = theme.get("category_id", "")
    color = CAT_COLORS.get(cat, _CAT_COLOR_DEFAULT)
    hook  = esc(theme.get("hook", CAT_HOOKS.get(cat, _HOOK_DEFAULT)))
    name  = esc(theme["name"].upper())
    sub   = esc(theme["subtitle"])

    # Dynamic loop label: "1 MIN LOOP", "2 MIN LOOP", or "60S LOOP" etc.
    if duration >= 60 and duration % 60 == 0:
        loop_label = f"{duration // 60} MIN LOOP"
    elif duration >= 60:
        loop_label = f"{duration // 60}:{duration % 60:02d} LOOP"
    else:
        loop_label = f"{duration}S LOOP"

    filters = [
        # ── Canvas ──────────────────────────────────────────────────────────
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={WIDTH}:{HEIGHT}",
        "setsar=1",

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
        # Hook text — 3-step alpha fade (full → dim → ghost)
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

        # ── Bottom gradient (3 overlapping semi-transparent layers) ─────────
        f"drawbox=x=0:y=1480:w={WIDTH}:h=440:color=black@0.28:t=fill",
        f"drawbox=x=0:y=1610:w={WIDTH}:h=310:color=black@0.52:t=fill",
        f"drawbox=x=0:y=1740:w={WIDTH}:h=180:color=black@0.78:t=fill",

        # ── Left category accent stripe ──────────────────────────────────────
        f"drawbox=x=0:y=1480:w=10:h=440:color={color}:t=fill",

        # ── Sound name ───────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{name}'"
        f":fontsize=84:fontcolor=white:x=(w-text_w)/2:y=1555"
        f":borderw=3:bordercolor={color}@0.40",

        # ── Thin separator line (category colour, between name and subtitle) ──
        f"drawbox=x=80:y=1652:w={WIDTH - 160}:h=1:color={color}@0.50:t=fill",

        # ── Subtitle ─────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{sub}'"
        f":fontsize=42:fontcolor=white@0.93:x=(w-text_w)/2:y=1668"
        f":borderw=2:bordercolor=black@0.70",

        # ── Progress bar track (full width, dark) ────────────────────────────
        f"drawbox=x=0:y=1855:w={WIDTH}:h=9:color=0x111111@0.85:t=fill",

        # ── Progress bar fill — 30 stepped segments ──────────────────────────
        # NOTE: in drawbox, the `t` parameter = thickness (not time!).
        # Time-based animation must use enable='gte(t,X)' where `t` IS time.
        *[
            f"drawbox=x={i * (WIDTH // 30)}:y=1855"
            f":w={WIDTH // 30 + 1}:h=9"
            f":color={color}:t=fill"
            f":enable='gte(t,{duration * i / 30:.2f})'"
            for i in range(30)
        ],

        # ── Loop badge ────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{loop_label}'"
        f":fontsize=28:fontcolor=white@0.60:x=(w-text_w)/2:y=1873",

        # ── Watermark — bottom-right, very subtle ─────────────────────────────
        f"drawtext=fontfile='{font}':text='Relax Sound'"
        f":fontsize=22:fontcolor=white@0.30:x=w-text_w-18:y=h-36"
        f":borderw=1:bordercolor=black@0.15",
    ]

    return ",".join(filters)


def build_video(theme: dict, media_path: Path, output_path: Path,
                duration: int = 120, audio_path: Path | None = None) -> Path:
    """
    Build a relaxation Short video.

    Audio priority:
      1. audio_path file provided → loop that file (real birds/rain/etc.)
      2. video with non-silent audio → use original video audio
      3. video without audio / image → lavfi synthetic fallback

    Args:
        theme:       Variant dict (name, subtitle, category_id, audio_lavfi, …)
        media_path:  Source video (.mp4) or image (.jpg/.png)
        output_path: Destination .mp4
        duration:    Seconds (default 120)
        audio_path:  Optional real audio file to loop
    """
    vf       = _build_vf(theme, duration)
    is_video = media_path.suffix.lower() == ".mp4"
    media_str = str(media_path.resolve()).replace("\\", "/")
    out_str   = str(output_path.resolve()).replace("\\", "/")

    # Lavfi fallback (used only when no real audio is available)
    audio_lavfi = theme.get("audio_lavfi", "anoisesrc=color=brown,volume=4.0")

    # fast preset + crf 26: ~30% smaller files, noticeably better visual quality
    # than ultrafast; well within GitHub Actions limits for 60-second Shorts.
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
        ffmpeg_args = [
            "ffmpeg", "-y",
            *input_args,
            "-stream_loop", "-1", "-i", audio_str,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]atrim=duration={duration},"
            f"volume=2.5,"
            f"afade=t=in:st=0:d=2,"
            f"afade=t=out:st={duration - 3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            *encode,
            out_str,
        ]

    elif is_video and _video_has_audio(media_path):
        # ── Case 2: video has usable original audio ───────────────────────────
        logger.info("Using video's own audio")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[0:a]aloop=loop=-1:size=2e+09,"
            f"atrim=duration={duration},"
            f"volume=2.5,"
            f"afade=t=in:st=0:d=2,"
            f"afade=t=out:st={duration - 3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            *encode,
            out_str,
        ]

    elif is_video:
        # ── Case 3: video but mute → lavfi ───────────────────────────────────
        logger.info("Video mute — lavfi fallback")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]afade=t=in:st=0:d=2,"
            f"afade=t=out:st={duration - 3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            *encode,
            out_str,
        ]

    else:
        # ── Case 4: still image + lavfi ──────────────────────────────────────
        logger.info("Image + lavfi fallback")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]afade=t=in:st=0:d=2,"
            f"afade=t=out:st={duration - 3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
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
