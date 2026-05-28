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
