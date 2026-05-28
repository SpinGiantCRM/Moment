"""Logging setup — file + (optional) systemd journal via stderr.

Provides :func:`setup_logging` which should be called once at app startup.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOG_DIR = os.path.expanduser("~/.local/share/clip-tray")
_LOG_FILE = os.path.join(_LOG_DIR, "clip-tray.log")
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure the root logger and return the application logger.

    * File handler writes to ``~/.local/share/clip-tray/clip-tray.log``
      with rotation at 10 MB (keeps 3 backups).
    * Stream handler writes to stderr for systemd journal integration.
    * Format: ``[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message``

    Args:
        verbose: If ``True``, set the log level to ``DEBUG``; otherwise ``INFO``.

    Returns:
        The configured root logger.
    """
    # Ensure the log directory exists
    Path(_LOG_DIR).mkdir(parents=True, exist_ok=True)

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
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
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
