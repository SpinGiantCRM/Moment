"""FFmpeg / FFprobe subprocess wrappers.

All functions raise :class:`FFmpegError` on non-zero exit.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cache binary availability checks
_ffmpeg_available: bool | None = None
_ffprobe_available: bool | None = None

# ---------------------------------------------------------------------------
# GPU-agnostic encoder matrix
# ---------------------------------------------------------------------------

# All supported encoders, grouped by vendor
_VENDOR_ENCODERS: dict[str, dict[str, str]] = {
    "nvidia": {
        "h264": "h264_nvenc",
        "hevc": "hevc_nvenc",
        "av1": "av1_nvenc",
    },
    "amd": {
        "h264": "h264_vaapi",
        "hevc": "hevc_vaapi",
        "av1": "av1_vaapi",
    },
    "intel": {
        "h264": "h264_qsv",
        "hevc": "hevc_qsv",
        "av1": "av1_qsv",
    },
}

# Priority order: best codec first per vendor (AV1 → HEVC → H.264)
_CODEC_PRIORITY: tuple[str, ...] = ("av1", "hevc", "h264")

# Cached result of detect_best_encoder()
_best_encoder: str | None = None


def detect_best_encoder() -> str:
    """Detect the best available hardware encoder, cached at module level.

    Strategy:
        1. Vendor detection via ``nvidia-smi`` → NVIDIA
           ``lspci | grep -i "vga.*amd"`` → AMD
           ``lspci | grep -i "vga.*intel"`` → Intel
        2. For known vendors, probe AV1 → HEVC → H.264 in priority order.
        3. If vendor is unknown or all vendor encoders fail,
           fall back to ffmpeg codec probe across all vendors.
        4. Software fallback: ``libx264`` (always available).

    Returns:
        One of: ``h264_nvenc``, ``hevc_nvenc``, ``av1_nvenc``,
        ``h264_vaapi``, ``hevc_vaapi``, ``av1_vaapi``,
        ``h264_qsv``, ``hevc_qsv``, ``av1_qsv``, or ``libx264``.
    """
    global _best_encoder
    if _best_encoder is not None:
        return _best_encoder

    vendor = _detect_vendor()
    logger.info("GPU vendor detected: %s", vendor or "unknown")

    # If vendor is known, try its encoders in priority order
    if vendor:
        encoder = _probe_vendor_encoders(vendor)
    else:
        encoder = None

    # Fallback: probe all encoders across all vendors
    if encoder is None:
        encoder = _probe_all_encoders()

    # Software fallback
    if encoder is None:
        encoder = "libx264"
        logger.info("No hardware encoder found; falling back to libx264")

    _best_encoder = encoder
    logger.info("Best encoder selected: %s", encoder)
    return encoder


def _detect_vendor() -> str | None:
    """Detect the GPU vendor via CLI tools.

    Returns:
        ``"nvidia"``, ``"amd"``, ``"intel"``, or ``None``.
    """
    # NVIDIA
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and "GPU" in result.stdout:
            return "nvidia"
    except (FileNotFoundError, OSError):
        pass

    # AMD
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            out = result.stdout.lower()
            if "vga" in out and "amd" in out:
                return "amd"
            if "vga" in out and "intel" in out:
                return "intel"
    except (FileNotFoundError, OSError):
        pass

    return None


def _probe_vendor_encoders(vendor: str) -> str | None:
    """Try each codec for *vendor* in priority order (AV1 → HEVC → H.264).

    Returns the first working encoder name or ``None``.
    """
    encoders = _VENDOR_ENCODERS.get(vendor, {})
    for codec in _CODEC_PRIORITY:
        encoder = encoders.get(codec)
        if encoder and _encoder_works(encoder):
            logger.info("Vendor encoder available: %s", encoder)
            return encoder
    return None


def _probe_all_encoders() -> str | None:
    """Probe every encoder across all vendors. Returns first working."""
    for vendor in ("nvidia", "amd", "intel"):
        for codec in _CODEC_PRIORITY:
            encoder = _VENDOR_ENCODERS[vendor].get(codec)
            if encoder and _encoder_works(encoder):
                logger.info("Fallback encoder found: %s", encoder)
                return encoder
    return None


def _encoder_works(encoder: str) -> bool:
    """Check whether ffmpeg supports *encoder* by asking it to list codecs.

    Uses ``ffmpeg -hide_banner -codecs`` filtered with grep.
    Runs with ``check=False`` — any failure means the encoder is not
    available.
    """
    try:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return False
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return False
        return encoder in result.stdout
    except (FileNotFoundError, OSError):
        return False


def reset_best_encoder() -> None:
    """Clear the cached encoder so ``detect_best_encoder()`` re-runs.

    Useful for testing or when the user changes the ``preferred_codec``
    setting to "auto".
    """
    global _best_encoder
    _best_encoder = None


class FFmpegError(RuntimeError):
    """Raised when an ffmpeg/ffprobe subprocess fails."""


def find_ffmpeg() -> str:
    """Return the path to the ``ffmpeg`` binary.

    Raises:
        FFmpegError: If ffmpeg is not on the system PATH.
    """
    global _ffmpeg_available
    if _ffmpeg_available is None:
        path = shutil.which("ffmpeg")
        if path is None:
            _ffmpeg_available = False
            raise FFmpegError("ffmpeg not found on system PATH")
        _ffmpeg_available = True
    elif not _ffmpeg_available:
        raise FFmpegError("ffmpeg not found on system PATH")
    return "ffmpeg"


def find_ffprobe() -> str:
    """Return the path to the ``ffprobe`` binary.

    Raises:
        FFmpegError: If ffprobe is not on the system PATH.
    """
    global _ffprobe_available
    if _ffprobe_available is None:
        path = shutil.which("ffprobe")
        if path is None:
            _ffprobe_available = False
            raise FFmpegError("ffprobe not found on system PATH")
        _ffprobe_available = True
    elif not _ffprobe_available:
        raise FFmpegError("ffprobe not found on system PATH")
    return "ffprobe"


def probe(path: str | Path) -> dict[str, Any]:
    """Run ffprobe on *path* and return parsed JSON metadata.

    Args:
        path: Media file to probe.

    Returns:
        Parsed JSON as a dictionary (``format`` + ``streams``).

    Raises:
        FFmpegError: On non-zero exit or missing ffprobe.
    """
    find_ffprobe()
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    logger.debug("Running ffprobe: %s", cmd)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed (code={result.returncode}): {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"ffprobe returned invalid JSON: {exc}") from exc


def encode(cmd: list[str]) -> subprocess.Popen[str]:
    """Launch an ffmpeg encode process and return the managed :class:`~subprocess.Popen`.

    Args:
        cmd: The ffmpeg command as a list of strings.  Must start with ``ffmpeg``.

    Returns:
        A :class:`~subprocess.Popen` for the running process.
    """
    find_ffmpeg()
    logger.debug("Running ffmpeg encode: %s", cmd)
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def thumbnail(input_path: str | Path, output_path: str | Path, time: float = 0.0) -> None:
    """Extract a single thumbnail frame from *input_path* at *time* seconds.

    Args:
        input_path: Source media file.
        output_path: Destination image path.
        time: Timestamp (seconds) to capture frame from.

    Raises:
        FFmpegError: On non-zero exit.
    """
    find_ffmpeg()
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(time),
        "-i", str(input_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path),
    ]
    logger.debug("Generating thumbnail: %s", cmd)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"thumbnail generation failed (code={result.returncode}): {result.stderr.strip()}")


def parse_fps(r_frame_rate: str) -> float:
    """Parse an ffprobe frame-rate string into a float.

    Examples:
        ``"30"`` → 30.0
        ``"30000/1001"`` → 29.97
    """
    try:
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/")
            return float(num) / float(den)
        return float(r_frame_rate)
    except (ValueError, ZeroDivisionError):
        return 0.0
