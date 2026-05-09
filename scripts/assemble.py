"""assemble.py — Build a relaxation Short with rich overlay.

Visual design:
  • Hook text for first 3s   — grabs the 2-second algorithm retention check
  • Category-coloured accent  — visual brand identity per sound type
  • Fake bottom gradient      — readability without covering the scenery
  • Loop badge                — sets expectation, reduces drop-off
  • Category label badge      — top-right pill for instant visual ID
  • Slot-based hook rotation  — 3 hooks/category so each post feels fresh
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
    "rain":        "0x2255BB",
    "forest":      "0x1A7A22",
    "ocean":       "0x006688",
    "fireplace":   "0xBB4400",
    "meditation":  "0x6633AA",
    "deep_sleep":  "0x1A1A66",
    "white_noise": "0x445566",
    "coffee_shop": "0x6B3A2A",
}
_CAT_COLOR_DEFAULT = "0x222233"

# ── Per-category color grading (ffmpeg eq filter) ─────────────────────────────
CAT_GRADE = {
    "rain":        "eq=saturation=0.90:gamma_r=0.93:gamma_b=1.08",
    "forest":      "eq=saturation=1.15:gamma_r=1.05:gamma_g=1.03",
    "ocean":       "eq=saturation=0.95:gamma_r=0.91:gamma_b=1.10",
    "fireplace":   "eq=saturation=1.20:gamma_r=1.12:gamma_b=0.88",
    "meditation":  "eq=saturation=0.82:gamma=1.06:gamma_b=1.05",
    "deep_sleep":  "eq=saturation=0.78:gamma=0.93:gamma_b=1.06",
    "white_noise": "eq=saturation=0.88:gamma=1.02",
    "coffee_shop": "eq=saturation=1.10:gamma_r=1.10:gamma_b=0.92",
}
_GRADE_DEFAULT = "eq=saturation=1.0"

# ── Per-category hook lines (shown for first 3 s) ─────────────────────────────
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


FONT_PATH = _detect_font()


def esc(s: str) -> str:
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
             .replace("$",  "\\$")
             .replace("\n", " "))


def _run_ffmpeg(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
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


def _build_vf(theme: dict, duration: int, slot: int = 0) -> str:
    font  = FONT_PATH
    cat   = theme.get("category_id", "")
    color = CAT_COLORS.get(cat, _CAT_COLOR_DEFAULT)
    grade = CAT_GRADE.get(cat, _GRADE_DEFAULT)

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
    cat_label = cat.upper().replace("_", " ")

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
        # ── Color grading ───────────────────────────────────────────────────────
        grade,
        # ── Vignette ──────────────────────────────────────────────────────────
        "vignette=angle=PI/5:mode=forward",
        # ── Sharpening ─────────────────────────────────────────────────────────
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.8"
        ":chroma_msize_x=3:chroma_msize_y=3:chroma_amount=0.4",
        # ── Hook banner (0–3 s) ──────────────────────────────────────────────
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.90:t=fill"
        f":enable='between(t,0,2.5)'",
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.40:t=fill"
        f":enable='between(t,2.5,2.8)'",
        f"drawbox=x=0:y=0:w={WIDTH}:h=195:color={color}@0.10:t=fill"
        f":enable='between(t,2.8,3.0)'",
        f"drawbox=x=0:y=188:w={WIDTH}:h=7:color={color}:t=fill"
        f":enable='between(t,0,2.5)'",
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
        # ── Bottom gradient ───────────────────────────────────────────────────
        f"drawbox=x=0:y=1480:w={WIDTH}:h=440:color=black@0.28:t=fill",
        f"drawbox=x=0:y=1610:w={WIDTH}:h=310:color=black@0.52:t=fill",
        f"drawbox=x=0:y=1740:w={WIDTH}:h=180:color=black@0.78:t=fill",
        # ── Left accent stripe ─────────────────────────────────────────────────
        f"drawbox=x=0:y=1480:w=10:h=440:color={color}:t=fill",
        # ── Name ──────────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{name}'"
        f":fontsize=84:fontcolor=white:x=(w-text_w)/2:y=1555"
        f":borderw=3:bordercolor={color}@0.40",
        # ── Separator ─────────────────────────────────────────────────────────
        f"drawbox=x=80:y=1652:w={WIDTH - 160}:h=1:color={color}@0.50:t=fill",
        # ── Subtitle ───────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{sub}'"
        f":fontsize=42:fontcolor=white@0.93:x=(w-text_w)/2:y=1668"
        f":borderw=2:bordercolor=black@0.70",
        # ── Loop badge ──────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='{loop_label}'"
        f":fontsize=28:fontcolor=white@0.55:x=(w-text_w)/2:y=1873",
        # ── Watermark ──────────────────────────────────────────────────────────
        f"drawtext=fontfile='{font}':text='Relax Sound'"
        f":fontsize=22:fontcolor=white@0.30:x=w-text_w-18:y=h-36"
        f":borderw=1:bordercolor=black@0.15",
        # ── Category label badge ───────────────────────────────────────────────
        f"drawbox=x={WIDTH - 210}:y=8:w=202:h=50:color=black@0.62:t=fill"
        f":enable='between(t,3.1,{duration})'",
        f"drawtext=fontfile='{font}':text='{cat_label}'"
        f":fontsize=25:fontcolor={color}@0.95"
        f":x=w-text_w-18:y=21"
        f":borderw=1:bordercolor=black@0.35"
        f":enable='between(t,3.1,{duration})'",
    ]

    return ",".join(filters)


def _seamless_audio_filter(src_label: str, duration: int, cf: int = 3,
                            volume: float = 2.5, has_aloop: bool = False) -> str:
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

    Audio priority (video is always muted — only visual background):
      1. audio_path (audio_file) exists  → loop that dedicated MP3
      2. audio_lavfi from theme          → synthesised sound (sine/noise)

    The video's own audio is intentionally ignored: Pixabay clips carry
    random stock music or ambient noise that doesn't match the variant's
    intended sound design.
    """
    CF = crossfade_dur

    vf        = _build_vf(theme, duration, slot)
    is_video  = media_path.suffix.lower() == ".mp4"
    media_str = str(media_path.resolve()).replace("\\", "/")
    out_str   = str(output_path.resolve()).replace("\\", "/")

    audio_lavfi = theme.get("audio_lavfi", "anoisesrc=color=brown,volume=4.0")

    encode = [
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
    ]

    if audio_path and audio_path.exists():
        # ── Case 1: dedicated audio file (rain.mp3, crackling_fire.mp3…) ────────
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

    elif is_video:
        # ── Case 2: video (muted) + lavfi synthesis ────────────────────────────
        # Video audio is ignored — lavfi defines the intended sound.
        logger.info(f"Video + lavfi: {audio_lavfi[:60]}")
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
        # ── Case 3: still image + lavfi ─────────────────────────────────────
        logger.info(f"Image + lavfi: {audio_lavfi[:60]}")
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
