"""Logging setup — file + (optional) systemd journal via stderr.

Provides :func:`setup_logging` which should be called once at app startup.
Log messages are sanitized to replace absolute home directory paths with ``~``.
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

_log_config: Config | None = None

# Home directory pattern for sanitization
_HOME = os.path.expanduser("~")


def _sanitize_path(msg: str) -> str:
    """Replace absolute home-directory paths with ``~``."""
    return msg.replace(_HOME, "~")


class _SanitizingFilter(logging.Filter):
    """Logging filter that sanitizes sensitive data in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize_path(str(record.msg))
        if record.args:
            record.args = tuple(
                _sanitize_path(str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True


def _get_config() -> Config | None:
    return _log_config


def set_log_config(config: Config | None) -> None:
    """Inject a Config instance so log paths honour user overrides."""
    global _log_config
    _log_config = config


def get_log_dir() -> str:
    """Return the log directory, respecting Config overrides."""
    cfg = _get_config()
    if cfg is not None:
        return cfg.get_path("log_dir")
    return _LOG_DIR


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure the root logger and return the application logger.

    * File handler writes to ``~/.local/share/moment/moment.log``
      with rotation at 10 MB (keeps 3 backups).  Log file is set to
      ``0o600`` (owner read/write only).
    * Stream handler writes to stderr for systemd journal integration.
    * All messages pass through a sanitizing filter that replaces
      absolute home-directory paths with ``~``.
    * Format: ``[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message``

    Args:
        verbose: If ``True``, set the log level to ``DEBUG``; otherwise ``INFO``.

    Returns:
        The configured root logger.
    """
    # Ensure the log directory exists
    log_dir = get_log_dir()
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
    sanitize_filter = _SanitizingFilter()

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
