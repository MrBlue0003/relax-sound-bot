"""assemble_long.py -- Build 11-hour landscape ambient videos for Relax Sound.

Structure of every video:
  [0:00 - 0:08]       Whisk intro  -- branded clip played as-is (with its own audio)
  [0:08 - 4:00:08]    Content      -- looping ambient video + audio (4 hours)
  [4:00:08 - 11:00:08] Black screen -- audio continues, screen dark for sleep

Audio transition: Whisk audio fades out over last 2 s → ambient fades in over 5 s.

Encoding:
  • 1280×720, 5 fps (ambient -- no detail lost at low fps)
  • ultrafast / CRF 28 (fast encode, small file, fine for ambient)
  • Black segment compresses to near-zero bytes in H.264
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Output canvas ─────────────────────────────────────────────────────────────
OUT_W   = 1280
OUT_H   = 720
OUT_FPS = 5

# ── Duration constants ────────────────────────────────────────────────────────
INTRO_DURATION   = 8
CONTENT_DURATION = 4 * 3600
BLACK_DURATION   = 7 * 3600
TOTAL_DURATION   = INTRO_DURATION + CONTENT_DURATION + BLACK_DURATION  # 39 608 s

# ── Encoding ──────────────────────────────────────────────────────────────────
VIDEO_PRESET  = "ultrafast"
VIDEO_CRF     = 28
AUDIO_BITRATE = "128k"
AUDIO_VOLUME  = 2.5


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
        logger.warning(f"Seamless loop prep failed -- using original: {audio_path.name}")
        return audio_path
    logger.info(f"Seamless loop baked: {out.name} ({dur:.1f}s, xfade={xfade:.1f}s)")
    return out


def extract_thumbnail(video_path: Path, output_path: Path) -> Path | None:
    """Extract a JPEG frame from 1 minute into the ambient content section."""
    timestamp = INTRO_DURATION + 60  # skip intro, grab a frame well inside the content
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", f"scale={OUT_W}:{OUT_H}",
        "-q:v", "2",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        logger.info(f"Thumbnail extracted: {output_path.name}")
        return output_path
    logger.warning(f"Thumbnail extraction failed: {r.stderr[-200:]}")
    return None


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


# Intro clip video filter -- play as-is, just scale/crop to canvas
_INTRO_VF = (
    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
    f"crop={OUT_W}:{OUT_H},"
    f"setsar=1,"
    f"fps=fps={OUT_FPS}"
)


def build_long_video(
    media_path: Path,
    audio_path: Path | None,
    output_path: Path,
    duration: int = TOTAL_DURATION,   # kept for backward-compat (ignored)
    title: str = "",
    category: str = "",
    audio_lavfi: str | None = None,
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
        logger.warning("whisk_intro.mp4 not found in assets -- skipping intro")
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

    has_intro    = intro_path is not None
    intro_vf_str = _INTRO_VF if has_intro else ""

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
    def _audio_filter(label: str, needs_aloop: bool, has_intro: bool = False) -> str:
        """Build ambient audio filter.

        has_intro=True:  Whisk clip audio plays first (8 s, fade-out last 2 s),
                         then ambient fades in over 5 s for the remaining duration.
        has_intro=False: ambient plays from t=0 with a 5-second fade-in.
        """
        if has_intro:
            aloop = "aloop=loop=-1:size=2e+09," if needs_aloop else ""
            ambient_dur = TOTAL_DURATION - INTRO_DURATION
            return (
                f"[0:a]atrim=0:{INTRO_DURATION},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={INTRO_DURATION - 2}:d=2[_intro_a];"
                f"{label}"
                f"{aloop}"
                f"atrim=duration={ambient_dur},asetpts=PTS-STARTPTS,"
                f"volume={AUDIO_VOLUME},"
                f"afade=t=in:st=0:d=5[_amb_a];"
                f"[_intro_a][_amb_a]concat=n=2:v=0:a=1[aout]"
            )
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

        fc_parts.append(_audio_filter(audio_lbl, needs_aloop=False, has_intro=has_intro))
        fc = ";".join(fc_parts)

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", fc,
               "-map", "[vout]", "-map", "[aout]"]
            + base_encode
            + ["-t", str(TOTAL_DURATION), out_str]
        )

    # ── Case 2: custom lavfi audio (e.g. 432Hz tone, pink noise) ─────────────
    elif audio_lavfi:
        _noise_dur = TOTAL_DURATION - INTRO_DURATION if has_intro else TOTAL_DURATION
        lavfi_src = f"{audio_lavfi},afade=t=in:st=0:d=5,atrim=duration={_noise_dur}"
        logger.info(f"Audio: lavfi custom ({audio_lavfi[:60]}...)")

        inputs = []
        if has_intro:
            inputs += ["-i", intro_str]
        if is_vid:
            inputs += ["-stream_loop", "-1", "-i", media_str]
        else:
            inputs += ["-loop", "1", "-i", media_str]
        inputs += ["-f", "lavfi", "-i", lavfi_src]

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

        if has_intro:
            fc_parts.append(
                f"[0:a]atrim=0:{INTRO_DURATION},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={INTRO_DURATION - 2}:d=2[_intro_a];"
                f"{audio_lbl}acopy[_amb_a];"
                f"[_intro_a][_amb_a]concat=n=2:v=0:a=1[aout]"
            )
        else:
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

    # ── Case 3: video with its own audio ─────────────────────────────────────
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
        fc_parts.append(_audio_filter(media_a, needs_aloop=True, has_intro=has_intro))
        fc = ";".join(fc_parts)

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", fc,
               "-map", "[vout]", "-map", "[aout]"]
            + base_encode
            + ["-t", str(TOTAL_DURATION), out_str]
        )

    # ── Case 4: no real audio → lavfi brown-noise fallback ───────────────────
    else:
        if is_vid:
            logger.warning("Video mute -- lavfi brown-noise fallback")
        else:
            logger.warning("Image -- lavfi brown-noise fallback")

        # Generate brown noise -- duration adjusted when intro clip is present
        _noise_dur = TOTAL_DURATION - INTRO_DURATION if has_intro else TOTAL_DURATION
        noise_src = (
            f"anoisesrc=c=brown:a=0.15:r=44100,"
            f"volume={AUDIO_VOLUME},"
            f"afade=t=in:st=0:d=5,"
            f"atrim=duration={_noise_dur}"
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
        if has_intro:
            fc_parts.append(
                f"[0:a]atrim=0:{INTRO_DURATION},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={INTRO_DURATION - 2}:d=2[_intro_a];"
                f"{audio_lbl}acopy[_amb_a];"
                f"[_intro_a][_amb_a]concat=n=2:v=0:a=1[aout]"
            )
        else:
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
