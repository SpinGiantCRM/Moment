"""System helpers — disk space, symlinks, local IP, OS info.

Does not import any GUI modules.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404 — required for TimeoutExpired exception type
import time
from pathlib import Path

from moment.utils.subprocess import ExternalCommandRunner

logger = logging.getLogger(__name__)

_command = ExternalCommandRunner()

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
    import math

    if num_bytes == 0:
        return "0 B"
    if num_bytes < 0:
        return f"{num_bytes} B"

    units = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
    i = int(math.floor(math.log(abs(num_bytes), 1024)))
    i = min(i, len(units) - 1)
    size = num_bytes / (1024 ** i)
    if i == 0:
        return f"{int(size)} {units[i]}"
    return f"{size:.1f} {units[i]}"


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
            result = _command.run(  # tokenized args, no shell=True
                [nvidia_smi],
                capture_output=True,
                timeout=5,
            )
            _nvidia_check = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            _nvidia_check = False

    _nvidia_timestamp = now
    return _nvidia_check


# Context-specific regex patterns for validate_arg
_VALIDATORS: dict[str, re.Pattern[str]] = {
    "device": re.compile(r"^[a-zA-Z0-9_., -]+$"),     # No forward slash (path traversal)
    "filename": re.compile(r"^[\w._-]+$"),              # Unicode-aware filenames
    "generic": re.compile(r"^[a-zA-Z0-9_., /-]+$"),    # Original permissive pattern
}


def validate_arg(
    value: str,
    pattern: str | None = None,
    context: str = "generic",
) -> str:
    """Validate a user-supplied value against an allowlist pattern.

    Used to guard values that are interpolated into subprocess command
    arguments or filtergraph strings.  Empty strings are returned as-is
    (callers treat them as "no override").

    If *pattern* is provided it takes precedence.  Otherwise the
    *context* key selects a pre-defined pattern from ``_VALIDATORS``.

    Args:
        value: The user-supplied string to validate.
        pattern: Regex pattern the value must fully match (optional).
            Overrides *context* when provided.
        context: Key into ``_VALIDATORS`` when *pattern* is ``None``.
            ``"device"`` blocks ``/``; ``"filename"`` is Unicode-aware;
            ``"generic"`` allows alphanumeric, dots, spaces, slashes.

    Returns:
        The validated string (passed through unchanged).

    Raises:
        ValueError: If *value* is non-empty and does not match.
    """
    if not value:
        return value

    if pattern is not None:
        regex = re.compile(pattern)
    else:
        regex = _VALIDATORS.get(context, _VALIDATORS["generic"])

    if not regex.fullmatch(value):
        raise ValueError(
            f"Invalid value {value!r}: must match pattern "
            f"{regex.pattern!r} (context={context})"
        )
    return value


def sanitize_stem(stem: str) -> str:
    """Remove path-traversal characters from a filename stem.

    Strips ``..``, leading ``/`` and ``._-``, and any character outside
    ``[\\w._-]`` (Unicode-aware) so the stem is safe to embed in a file path.
    CJK, Cyrillic, Arabic, and other scripts are preserved.

    Args:
        stem: Raw filename stem (e.g. from ``clip.stem``).

    Returns:
        Sanitised stem safe for path construction.
    """
    import re
    # Remove parent-dir traversal and root-anchored / path-separator components
    cleaned = stem.replace("..", "_").lstrip("/").lstrip("\\")
    # Strip leading dots, underscores, and hyphens (prevents hidden files)
    cleaned = cleaned.lstrip("._-")
    # Keep word characters (Unicode-aware), dots, underscores, and hyphens
    cleaned = re.sub(r"[^\w.-]", "_", cleaned)
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


# Cache for get_local_ip (300-second TTL)
_local_ip_cache: str | None = None
_local_ip_cache_time: float = 0.0
_LOCAL_IP_CACHE_TTL: float = 300.0


def get_local_ip() -> str:
    """Return the primary local IP address, or ``"127.0.0.1"`` if unavailable.

    Result is cached for 300 seconds to avoid repeated socket connections
    (which can add 100ms+ delay when offline).
    """
    import socket

    global _local_ip_cache, _local_ip_cache_time

    now = time.monotonic()
    if _local_ip_cache is not None and (now - _local_ip_cache_time) < _LOCAL_IP_CACHE_TTL:
        return _local_ip_cache

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            # Connect to a non-existent address to get the local IP
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            _local_ip_cache = ip
            _local_ip_cache_time = now
            return ip
    except (OSError, IndexError):
        pass

    # Fallback: try hostname resolution
    try:
        ip = socket.gethostbyname(socket.gethostname())
        _local_ip_cache = ip
        _local_ip_cache_time = now
        return ip
    except OSError:
        _local_ip_cache = "127.0.0.1"
        _local_ip_cache_time = now
        return "127.0.0.1"


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
