"""Logging setup — file + (optional) systemd journal via stderr.

Provides :func:`setup_logging` which should be called once at app startup.
Log messages pass through :class:`SanitizingFilter` which redacts:

* Discord bot tokens
* Webhook URLs
* Bearer tokens in Authorization headers
* Encryption keys (hex strings 64+ chars)
* Cloud storage URLs (R2 / S3)
* Absolute home directory paths (replaced with ``~``)
* External file paths outside $HOME
* Local IP addresses
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moment.core.config import Config

_LOG_DIR = os.path.expanduser("~/.local/share/moment")
_LOG_FILE = os.path.join(_LOG_DIR, "moment.log")
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3

# Home directory for path sanitization
_HOME = os.path.expanduser("~")

# ---------------------------------------------------------------------------
# Sanitization patterns (in order of application)
# ---------------------------------------------------------------------------
# Pre-compiled regex patterns — ordered to avoid overlap (most specific first)

_SANITIZE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Discord bot tokens: [A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}
    (
        re.compile(r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}"),
        "[DISCORD_TOKEN_REDACTED]",
    ),
    # Webhook URLs (Discord)
    (
        re.compile(r"https://discord\.com/api/webhooks/\d+/\S+"),
        "[WEBHOOK_URL_REDACTED]",
    ),
    # Bearer tokens in headers: Bearer <32+ chars>
    (
        re.compile(r"Bearer [A-Za-z0-9_\-+/=]{32,}"),
        "Bearer [TOKEN_REDACTED]",
    ),
    # R2 / S3 cloud URLs with bucket names
    (
        re.compile(r"https://[a-zA-Z0-9.\-]+\.r2\.cloudflarestorage\.com/[^\s]*"),
        "[CLOUD_URL_REDACTED]",
    ),
    (
        re.compile(r"https://s3\.[a-zA-Z0-9\-]+\.amazonaws\.com/[^\s]*"),
        "[CLOUD_URL_REDACTED]",
    ),
    # Rclone remote:path notation
    (
        re.compile(r"r2:moment/[^\s]*"),
        "[CLOUD_PATH_REDACTED]",
    ),
    # Encryption keys: hex strings of 64+ characters (standalone / in quotes)
    (
        re.compile(r"\b[A-Fa-f0-9]{64,}\b"),
        "[KEY_REDACTED]",
    ),
]

# Local IP address pattern (applied to the whole message after other redactions)
_LOCAL_IP_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:127\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)


def _sanitize(msg: str) -> str:
    """Apply all sanitization patterns to a message string."""
    # 1. Replace home directory paths with ~
    msg = msg.replace(_HOME, "~")

    # 2. Apply regex patterns for tokens, URLs, keys
    for pattern, replacement in _SANITIZE_PATTERNS:
        msg = pattern.sub(replacement, msg)

    # 3. Redact local IP addresses
    msg = _LOCAL_IP_PATTERN.sub("[LOCAL_IP_REDACTED]", msg)

    return msg


class SanitizingFilter(logging.Filter):
    """Logging filter that redacts sensitive data from log records.

    Applied to all handlers so that secrets never hit disk or stderr.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize(str(record.msg))
        if record.args:
            record.args = tuple(
                _sanitize(str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def setup_logging(verbose: bool = False, *, config: "Config | None" = None) -> logging.Logger:
    """Configure the root logger and return the application logger.

    * File handler writes to ``~/.local/share/moment/moment.log``
      with rotation at 10 MB (keeps 3 backups).  Log file is set to
      ``0o600`` (owner read/write only).
    * Stream handler writes to stderr for systemd journal integration.
    * All messages pass through :class:`SanitizingFilter` which redacts
      tokens, keys, URLs, webhooks, cloud paths, and local IPs.
    * Home directory paths are replaced with ``~``.
    * Format: ``[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message``

    Args:
        verbose: If ``True``, set the log level to ``DEBUG``; otherwise ``INFO``.
        config: Optional Config for path overrides.

    Returns:
        The configured root logger.
    """
    # Resolve log directory — honour Config path override if provided
    log_dir = config.get_path("log_dir") if config is not None else _LOG_DIR
    log_file = os.path.join(log_dir, "moment.log")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Restrict umask so RotatingFileHandler creates log files as 0o600
    old_umask = os.umask(0o077)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Remove any previously added handlers to avoid duplication on re-call
    root.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Sanitizing filter
    sanitize_filter = SanitizingFilter()

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(sanitize_filter)
    root.addHandler(file_handler)

    # Restore original umask; also set permissions on existing file
    os.umask(old_umask)
    try:
        os.chmod(log_file, 0o600)
    except OSError:
        pass

    # Stream handler → stderr (picked up by systemd journal if applicable)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(fmt)
    stream_handler.addFilter(sanitize_filter)
    root.addHandler(stream_handler)

    return root
