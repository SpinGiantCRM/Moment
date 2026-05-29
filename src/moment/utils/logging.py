"""Logging setup — file + (optional) systemd journal via stderr.

Provides :func:`setup_logging` which should be called once at app startup.
"""

from __future__ import annotations

import logging
import os
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
      with rotation at 10 MB (keeps 3 backups).
    * Stream handler writes to stderr for systemd journal integration.
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

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Remove any previously added handlers to avoid duplication on re-call
    root.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Stream handler → stderr (picked up by systemd journal if applicable)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    return root
