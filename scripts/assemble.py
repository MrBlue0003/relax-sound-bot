"""assemble.py — Build a 90-second relaxation short with text overlay."""
import logging
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920


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
    """Escape text for ffmpeg drawtext filter."""
    return (s.replace("\\", "\\\\")
             .replace("'", "\u2019")
             .replace('"', "\u201c")
             .replace(":", "\\:")
             .replace("[", "\\[")
             .replace("]", "\\]")
             .replace(",", " ")
             .replace(";", " ")
             .replace("%", "%%")
             .replace("$", "\\$")
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
    """Return True if video has an audio stream with actual non-silent content.
    Checks both stream existence AND that mean volume is above -91 dBFS (not silence).
    """
    try:
        # Step 1: check if audio stream exists
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        if "audio" not in r.stdout:
            return False

        # Step 2: measure actual volume — detect silent streams
        r2 = subprocess.run(
            ["ffmpeg", "-i", str(video_path),
             "-t", "10",  # sample first 10 seconds
             "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        output = r2.stderr
        # Look for mean_volume line
        for line in output.splitlines():
            if "mean_volume" in line:
                # e.g. "mean_volume: -91.0 dB" means silence
                try:
                    db = float(line.split(":")[1].strip().replace(" dB", ""))
                    if db < -90.0:
                        logger.info(f"Audio stream detected but silent (mean={db:.1f}dB) — using lavfi fallback")
                        return False
                    logger.info(f"Audio stream OK (mean={db:.1f}dB)")
                    return True
                except Exception:
                    pass
        # If volumedetect didn't output mean_volume, assume audio is OK
        return True
    except Exception:
        return False


def build_video(theme: dict, media_path: Path, output_path: Path,
                duration: int = 90, audio_path: Path | None = None) -> Path:
    """
    Build a relaxation video.
    - media_path .mp4 + audio_path: loop video visuals, use audio_path as sound
    - media_path .mp4 (no audio_path): loop video with original audio (or noise if mute)
    - media_path .jpg/.png + audio_path: image bg + audio_path
    - media_path .jpg/.png (no audio_path): image bg + anoisesrc generated noise
    """
    font = FONT_PATH
    name_text = esc(theme["name"].upper())
    subtitle_text = esc(theme["subtitle"].upper())

    top_box_y = 60
    top_box_h = 200
    name_y = top_box_y + 30
    bot_box_y = HEIGHT - 155
    bot_box_h = 130
    sub_y = bot_box_y + 32

    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"drawbox=x=0:y={top_box_y}:w={WIDTH}:h={top_box_h}:color=black@0.72:t=fill,"
        f"drawtext=fontfile='{font}':text='{name_text}':"
        f"fontcolor=white:fontsize=82:x=(w-text_w)/2:y={name_y}:"
        f"borderw=4:bordercolor=black@0.8,"
        f"drawbox=x=0:y={bot_box_y}:w={WIDTH}:h={bot_box_h}:color=black@0.65:t=fill,"
        f"drawtext=fontfile='{font}':text='{subtitle_text}':"
        f"fontcolor=white@0.95:fontsize=44:x=(w-text_w)/2:y={sub_y}:"
        f"borderw=2:bordercolor=black"
    )

    is_video = media_path.suffix.lower() == ".mp4"
    media_str = str(media_path.resolve()).replace("\\", "/")
    out_str = str(output_path.resolve()).replace("\\", "/")

    # Lavfi fallback — only used when video has no audio or media is image
    audio_lavfi = theme.get("audio_lavfi", "anoisesrc=color=brown,volume=4.0")

    if is_video and _video_has_audio(media_path):
        # ── Use original video audio — birds chirp, rain falls, waves crash ──
        logger.info("Using original video audio (matches visuals)")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[0:a]aloop=loop=-1:size=2e+09,atrim=duration={duration},"
            f"volume=2.5,afade=t=in:st=0:d=2,afade=t=out:st={duration-3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_str,
        ]
    elif is_video:
        # ── Video has no audio → synthetic fallback ──
        logger.info("Video mute — using synthetic lavfi audio")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]afade=t=in:st=0:d=2,afade=t=out:st={duration-3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_str,
        ]
    else:
        # ── Image + synthetic audio ──
        logger.info("Image input — using synthetic lavfi audio")
        ffmpeg_args = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", media_str,
            "-f", "lavfi", "-i", audio_lavfi,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]{vf}[vout];"
            f"[1:a]afade=t=in:st=0:d=2,afade=t=out:st={duration-3}:d=3[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            out_str,
        ]

    logger.info(f"Building video: {theme['name']} ({duration}s)")
    result = _run_ffmpeg(ffmpeg_args, output_path.parent)

    if result.returncode != 0:
        logger.error(f"FFmpeg error:\n{result.stderr[-1000:]}")
        raise RuntimeError(f"Video build failed for theme: {theme['name']}")

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"Video done: {output_path.name} ({size_mb:.1f}MB)")
    return output_path
