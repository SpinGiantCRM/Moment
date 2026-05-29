"""System helpers — disk space, symlinks, local IP, OS info.

Does not import any GUI modules.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache for is_nvidia_gpu (60-second TTL)
_nvidia_check: bool | None = None
_nvidia_timestamp: float = 0.0
_NVIDIA_CACHE_TTL: float = 60.0


def disk_usage(path: str | Path) -> tuple[int, int, int]:
    """Return (total, used, free) in bytes for the filesystem containing *path*.

    Args:
        path: Any path on the target filesystem.

    Returns:
        ``(total_bytes, used_bytes, free_bytes)``
    """
    usage = shutil.disk_usage(str(path))
    return usage.total, usage.used, usage.free


def ensure_dir(path: str | Path) -> Path:
    """Create directory (including parents) and return a :class:`Path` to it.

    Args:
        path: Directory to create.

    Returns:
        Resolved :class:`Path` to the directory.
    """
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def human_size(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string (e.g. ``"12.5 MB"``).

    Args:
        num_bytes: Size in bytes.

    Returns:
        Formatted string.
    """
    if num_bytes < 0:
        return f"{num_bytes} B"

    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(num_bytes) < 1024.0:
            if unit == "B":
                return f"{int(num_bytes)} {unit}"
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0

    return f"{num_bytes:.1f} EB"


def is_nvidia_gpu() -> bool:
    """Return ``True`` if an NVIDIA GPU is present and ``nvidia-smi`` is available.

    Result is cached for 60 seconds.
    """
    global _nvidia_check, _nvidia_timestamp

    now = time.monotonic()
    if _nvidia_check is not None and (now - _nvidia_timestamp) < _NVIDIA_CACHE_TTL:
        return _nvidia_check

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        _nvidia_check = False
    else:
        try:
            result = subprocess.run(
                [nvidia_smi],
                capture_output=True,
                timeout=5,
            )
            _nvidia_check = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            _nvidia_check = False

    _nvidia_timestamp = now
    return _nvidia_check


def sanitize_stem(stem: str) -> str:
    """Remove path-traversal characters from a filename stem.

    Strips ``..``, leading ``/``, and any character outside
    ``[a-zA-Z0-9._-]`` so the stem is safe to embed in a file path.

    Args:
        stem: Raw filename stem (e.g. from ``clip.stem``).

    Returns:
        Sanitised stem safe for path construction.
    """
    import re
    # Remove parent-dir traversal and root-anchored components
    cleaned = stem.replace("..", "").lstrip("/").lstrip("\\")
    # Keep only safe characters
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", cleaned)
    # Collapse runs of underscores
    cleaned = re.sub(r"_+", "_", cleaned)
    # Guard against empty result
    return cleaned or "clip"


def find_binary(name: str) -> str | None:
    """Locate a binary on the system ``PATH``.

    Args:
        name: Binary name (e.g. ``"ffmpeg"``).

    Returns:
        Absolute path to the binary, or ``None`` if not found.
    """
    return shutil.which(name)


def get_local_ip() -> str | None:
    """Return the primary local IP address, or ``None`` if unavailable."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.1)
            # Connect to a non-existent address to get the local IP
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except (OSError, IndexError):
        pass

    # Fallback: try hostname resolution
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return None


def get_os_name() -> str:
    """Return a short human-readable OS description."""
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except FileNotFoundError:
        pass
    return "Linux"
