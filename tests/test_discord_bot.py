"""Tests for moment.core.discord_bot — DiscordBot + helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from moment.core.discord_bot import (
    DiscordBot,
    _fmt_duration,
    _fmt_size,
    _get_discord_token,
    _status_emoji,
    AUTO_START_DISABLED,
    AUTO_START_AUTO,
    AUTO_START_MANUAL,
)
from moment.core.models import Clip, ClipStatus, ClipType


class TestStatusEmoji:
    def test_status_emojis(self):
        clip = MagicMock(status=ClipStatus.UPLOADED)
        assert "✅" in _status_emoji(clip)
        clip.status = ClipStatus.ENCODING
        assert "🔄" in _status_emoji(clip)
        clip.status = ClipStatus.UPLOADING
        assert "⬆️" in _status_emoji(clip)
        clip.status = ClipStatus.DONE
        assert "✔️" in _status_emoji(clip)
        clip.status = ClipStatus.ERROR
        assert "❌" in _status_emoji(clip)
        clip.status = ClipStatus.CORRUPT
        assert "💥" in _status_emoji(clip)


class TestFmtDuration:
    def test_formats_seconds(self):
        assert _fmt_duration(0) == "0:00"
        assert _fmt_duration(30) == "0:30"
        assert _fmt_duration(65) == "1:05"
        assert _fmt_duration(3661) == "61:01"


class TestFmtSize:
    def test_formats_bytes(self):
        result = _fmt_size(0)
        assert "0" in result
        assert "B" in result

    def test_formats_kilobytes(self):
        result = _fmt_size(2048)
        assert "KB" in result or "kB" in result.upper()

    def test_formats_megabytes(self):
        result = _fmt_size(2097152)
        assert "MB" in result or "mB" in result.upper()


class TestGetDiscordToken:
    @patch.dict(os.environ, {"MOMENT_DISCORD_TOKEN": "env-token"})
    def test_from_env(self):
        token = _get_discord_token()
        assert token == "env-token"

    @patch.dict(os.environ, {}, clear=True)
    def test_keyring_import_error(self):
        # When keyring is not importable, returns empty
        with patch.dict("sys.modules", {"keyring": None}):
            token = _get_discord_token()
            assert token == ""

    @patch.dict(os.environ, {}, clear=True)
    @patch("moment.core.discord_bot.keyring", None, create=True)
    def test_no_token_env_or_keyring(self):
        token = _get_discord_token()
        assert token == ""


class TestDiscordBotInit:
    def test_create(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        assert bot.is_running is False

    def test_is_available(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        assert isinstance(bot.is_available, bool)

    def test_auto_start_mode(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "auto"
        bot = DiscordBot(store, config)
        assert bot.auto_start_mode == "auto"


class TestDiscordBotStart:
    def test_start_no_token(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        bot.start()
        assert bot.is_running is False

    def test_already_running(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        bot._running = True
        bot.start()
        assert bot.is_running is True


class TestDiscordBotAutoStart:
    def test_auto_start_disabled(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = AUTO_START_DISABLED
        bot = DiscordBot(store, config)
        bot.start = MagicMock()
        bot.auto_start()
        bot.start.assert_not_called()

    def test_auto_start_manual(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = AUTO_START_MANUAL
        bot = DiscordBot(store, config)
        bot.start = MagicMock()
        bot.auto_start()
        bot.start.assert_not_called()

    def test_auto_start_auto(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = AUTO_START_AUTO
        bot = DiscordBot(store, config)
        bot.start = MagicMock()
        bot.auto_start()
        bot.start.assert_called_once()


class TestDiscordBotStop:
    def test_stop_when_not_running(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        bot.stop()


class TestDiscordBotSendWebhook:
    def test_send_webhook_disabled(self):
        store = MagicMock()
        config = MagicMock()
        config.get.return_value = "disabled"
        bot = DiscordBot(store, config)
        clip = Clip(
            id="test",
            stem="test",
            source_path="/tmp/test.mp4",
            duration=10.0,
            file_size=1000000,
            title="Test",
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        webhook = MagicMock()
        webhook.enabled = False
        result = bot.send_webhook(clip, webhook)
        assert result is False
