"""Tests for utils/logging.py."""

from __future__ import annotations

import logging
import os

from moment.utils.logging import SanitizingFilter, _sanitize, setup_logging


class TestSanitize:
    """Spec 25 — log path sanitization."""

    def test_home_dir_replaced_with_tilde(self) -> None:
        home = os.path.expanduser("~")
        result = _sanitize(f"Source: {home}/Videos/Moment/clip.mkv")
        assert home not in result
        assert "~/Videos/Moment/clip.mkv" in result

    def test_relative_paths_unchanged(self) -> None:
        result = _sanitize("clip saved to ./data/test.mkv")
        assert result == "clip saved to ./data/test.mkv"

    def test_no_path_no_change(self) -> None:
        result = _sanitize("Encoding started")
        assert result == "Encoding started"

    def test_multiple_home_fragments(self) -> None:
        home = os.path.expanduser("~")
        msg = f"Moved {home}/a to {home}/b"
        result = _sanitize(msg)
        assert result == "Moved ~/a to ~/b"

    def test_discord_token_redacted(self) -> None:
        result = _sanitize("Token: MjE0MjUzODg0MjY4MjY0MTI4.Gzabcd.some_random_characters_here1234")
        assert "[DISCORD_TOKEN_REDACTED]" in result
        assert "MjE0MjUzODg0MjY4MjY0MTI4" not in result

    def test_webhook_url_redacted(self) -> None:
        result = _sanitize(
            "Sending to https://discord.com/api/webhooks/1234567890/abcdefghijklmnopqrstuvwxyz"
        )
        assert "[WEBHOOK_URL_REDACTED]" in result
        assert "discord.com/api/webhooks" not in result

    def test_bearer_token_redacted(self) -> None:
        result = _sanitize("Auth: Bearer abcdefghijklmnopqrstuvwxyz1234567890ABCDEF")
        assert "Bearer [TOKEN_REDACTED]" in result

    def test_hex_key_redacted(self) -> None:
        key = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2"
        result = _sanitize(f"Key: {key}")
        assert "[KEY_REDACTED]" in result
        assert key not in result

    def test_cloud_url_redacted(self) -> None:
        result = _sanitize(
            "Uploaded to https://my-bucket.r2.cloudflarestorage.com/path/to/file.mp4"
        )
        assert "[CLOUD_URL_REDACTED]" in result

    def test_s3_url_redacted(self) -> None:
        result = _sanitize("Stored at https://s3.us-east-1.amazonaws.com/bucket/key.mp4")
        assert "[CLOUD_URL_REDACTED]" in result

    def test_rclone_path_redacted(self) -> None:
        result = _sanitize("Pushing r2:moment/clips/my-clip.mp4")
        assert "[CLOUD_PATH_REDACTED]" in result

    def test_local_ip_redacted(self) -> None:
        result = _sanitize("Listening on 192.168.1.100:8080")
        assert "[LOCAL_IP_REDACTED]" in result
        assert "192.168.1.100" not in result


class TestSanitizingFilter:
    """Spec 25 — SanitizingFilter applied to log records."""

    def test_filter_sanitizes_msg(self) -> None:
        home = os.path.expanduser("~")
        f = SanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Path: {home}/Videos/test.mkv",
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True
        assert record.msg == "Path: ~/Videos/test.mkv"

    def test_filter_sanitizes_args(self) -> None:
        home = os.path.expanduser("~")
        f = SanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Copied %s → %s",
            args=(f"{home}/a.mkv", f"{home}/b.mkv"),
            exc_info=None,
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
        """Spec 25: All handlers should have a SanitizingFilter."""
        logger = setup_logging()
        for handler in logger.handlers:
            has_filter = any(isinstance(f, SanitizingFilter) for f in handler.filters)
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
