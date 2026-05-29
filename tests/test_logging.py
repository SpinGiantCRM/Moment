"""Tests for utils/logging.py."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from moment.utils.logging import setup_logging, _sanitize_path, _SanitizingFilter


class TestSanitizePath:
    """Spec 25 — log path sanitization."""

    def test_home_dir_replaced_with_tilde(self) -> None:
        home = os.path.expanduser("~")
        result = _sanitize_path(f"Source: {home}/Videos/Moment/clip.mkv")
        assert home not in result
        assert "~/Videos/Moment/clip.mkv" in result

    def test_relative_paths_unchanged(self) -> None:
        result = _sanitize_path("clip saved to ./data/test.mkv")
        assert result == "clip saved to ./data/test.mkv"

    def test_no_path_no_change(self) -> None:
        result = _sanitize_path("Encoding started")
        assert result == "Encoding started"

    def test_multiple_home_fragments(self) -> None:
        home = os.path.expanduser("~")
        msg = f"Moved {home}/a to {home}/b"
        result = _sanitize_path(msg)
        assert result == "Moved ~/a to ~/b"


class TestSanitizingFilter:
    """Spec 25 — SanitizingFilter applied to log records."""

    def test_filter_sanitizes_msg(self) -> None:
        home = os.path.expanduser("~")
        f = _SanitizingFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=f"Path: {home}/Videos/test.mkv", args=(), exc_info=None,
        )
        assert f.filter(record) is True
        assert record.msg == "Path: ~/Videos/test.mkv"

    def test_filter_sanitizes_args(self) -> None:
        home = os.path.expanduser("~")
        f = _SanitizingFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Copied %s → %s", args=(f"{home}/a.mkv", f"{home}/b.mkv"), exc_info=None,
        )
        assert f.filter(record) is True
        assert record.args == ("~/a.mkv", "~/b.mkv")


class TestSetupLogging:
    def test_returns_logger(self) -> None:
        logger = setup_logging(verbose=False)
        assert isinstance(logger, logging.Logger)

    def test_verbose_sets_debug(self) -> None:
        logger = setup_logging(verbose=True)
        assert logger.level == logging.DEBUG

    def test_non_verbose_sets_info(self) -> None:
        logger = setup_logging(verbose=False)
        assert logger.level == logging.INFO

    def test_handlers_configured(self) -> None:
        logger = setup_logging()
        assert len(logger.handlers) >= 2  # file + stream

    def test_handlers_have_sanitizing_filter(self) -> None:
        """Spec 25: All handlers should have a _SanitizingFilter."""
        logger = setup_logging()
        for handler in logger.handlers:
            has_filter = any(
                isinstance(f, _SanitizingFilter) for f in handler.filters
            )
            assert has_filter, f"Handler {handler} missing sanitizing filter"

    def test_log_file_0600_permissions(self) -> None:
        """Spec 25: Log file should be owner read/write only."""
        logger = setup_logging()
        # Find the file handler
        from logging.handlers import RotatingFileHandler
        fh = next(
            (h for h in logger.handlers if isinstance(h, RotatingFileHandler)),
            None,
        )
        if fh is not None:
            path = fh.baseFilename
            if os.path.isfile(path):
                mode = os.stat(path).st_mode & 0o777
                assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
