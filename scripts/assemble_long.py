"""assemble_long.py — Build 1-hour landscape ambient videos for Relax Sound.

Design:
  • 16:9 (1280×720) — standard YouTube long-form format
  • Loops source video + audio file to fill target duration
  • Ultra-low encoding settings (ultrafast/crf 28) for fast GH Actions runtime
  • Subtle fade-in / fade-out on audio only
  • No text overlays — pure ambient experience
  • Falls back to looped still image if no video available
"""

import logging
import os
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Output canvas ─────────────────────────────────────────────────────────────
OUT_W = 1280
OUT_H = 720
FPS   = 30

# ── Encoding ──────────────────────────────────────────────────────────────────
VIDEO_PRESET = "ultrafast"
VIDEO_CRF    = 28          # good enough for ambient footage; keeps file tiny
AUDIO_BITRATE = "128k"

AUDIO_FADE = 5             # seconds for audio fade-in / fade-out
AUDIO_VOLUME = 2.5         # boost — most Pixabay clips are quiet


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


def _video_has_audio(video_path: Path) -> bool:
    """Return True if video has a real audio stream (non-silent)."""
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
             "-t", "10", "-af", "volumedetect", "-f", "null", "/dev/null"],
            capture_output=True, text=True, timeout=30,
        )
        output = r2.stderr
        if "mean_volume" in output:
            for line in output.splitlines():
                if "mean_volume" in line:
                    try:
                        vol = float(line.split(":")[1].strip().replace(" dB", ""))
                        return vol > -91.0
                    except (ValueError, IndexError):
                        pass
        return True
    except Exception:
        return False


def _is_video(media_path: Path) -> bool:
    return media_path.suffix.lower() in (".mp4", ".mov", ".avi", ".webm", ".mkv")


def build_long_video(
    media_path: Path,
    audio_path: Path | None,
    output_path: Path,
    duration: int = 3600,
    title: str = "",
) -> Path:
    """
    Build a looped ambient long-form video.

    Args:
        media_path:   Source video or image to loop for the full duration.
        audio_path:   Real audio file (MP3/WAV) to loop. If None, uses video
                      audio (if present) or a lavfi brown-noise fallback.
        output_path:  Destination MP4 path.
        duration:     Total length in seconds (default 3600 = 1 hour).
        title:        Unused — reserved for future title-card overlay.

    Returns:
        output_path on success; raises RuntimeError on failure.
    """
    is_vid = _is_video(media_path)
    out_str   = str(output_path.resolve()).replace("\\", "/")
    media_str = str(media_path.resolve()).replace("\\", "/")

    fade_out_start = duration - AUDIO_FADE
    af_chain = (
        f"volume={AUDIO_VOLUME},"
        f"afade=t=in:st=0:d={AUDIO_FADE},"
        f"afade=t=out:st={fade_out_start}:d={AUDIO_FADE}"
    )

    # Scale+crop filter to fit output canvas
    vf = (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},"
        f"setsar=1,"
        f"fps={FPS}"
    )

    base_encode = [
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-t", str(duration),
        out_str,
    ]

    # ── Case 1: explicit real audio file ─────────────────────────────────────
    if audio_path and audio_path.exists():
        audio_str = str(audio_path.resolve()).replace("\\", "/")
        logger.info(f"Audio override: {audio_path.name} (looped to {duration}s)")

        if is_vid:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", media_str,
                "-stream_loop", "-1", "-i", audio_str,
                "-vf", vf,
                "-af", af_chain,
                "-map", "0:v:0",
                "-map", "1:a:0",
            ] + base_encode
        else:
            # Still image — use -loop 1 (much smaller output, since no motion)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", media_str,
                "-stream_loop", "-1", "-i", audio_str,
                "-vf", vf,
                "-af", af_chain,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-tune", "stillimage",
            ] + base_encode

    # ── Case 2: video with its own audio ─────────────────────────────────────
    elif is_vid and _video_has_audio(media_path):
        logger.info("Using video's own audio (looped)")
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-vf", vf,
            "-af", af_chain,
            "-map", "0:v:0",
            "-map", "0:a:0",
        ] + base_encode

    # ── Case 3: video without audio — lavfi brown-noise fallback ─────────────
    elif is_vid:
        logger.warning("Video has no audio — using lavfi brownnoise fallback")
        noise_src = (
            f"anoisesrc=c=brown:a=0.15:r=44100,volume={AUDIO_VOLUME},"
            f"afade=t=in:st=0:d={AUDIO_FADE},"
            f"afade=t=out:st={fade_out_start}:d={AUDIO_FADE},"
            f"atrim=duration={duration}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", media_str,
            "-f", "lavfi", "-i", noise_src,
            "-vf", vf,
            "-map", "0:v:0",
            "-map", "1:a:0",
        ] + base_encode

    # ── Case 4: still image + lavfi ──────────────────────────────────────────
    else:
        logger.warning("Image + lavfi brownnoise (no audio file available)")
        noise_src = (
            f"anoisesrc=c=brown:a=0.15:r=44100,volume={AUDIO_VOLUME},"
            f"afade=t=in:st=0:d={AUDIO_FADE},"
            f"afade=t=out:st={fade_out_start}:d={AUDIO_FADE},"
            f"atrim=duration={duration}"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", media_str,
            "-f", "lavfi", "-i", noise_src,
            "-vf", vf,
            "-tune", "stillimage",
            "-map", "0:v:0",
            "-map", "1:a:0",
        ] + base_encode

    logger.info(f"Encoding {duration}s ambient video → {output_path.name}")
    logger.info(f"ffmpeg: {' '.join(cmd[:12])} ...")   # log abbreviated

    timeout_s = max(duration * 2, 3600)   # at least 1h; ≥2× realtime headroom
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

    if result.returncode != 0:
        logger.error(f"ffmpeg stderr (last 4000):\n{result.stderr[-4000:]}")
        raise RuntimeError(f"ffmpeg failed building long video: {output_path.name}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(f"Long video ready: {output_path.name} ({size_mb:.1f} MB)")
    return output_path
