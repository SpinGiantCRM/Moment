"""Tests for core/discord_bot.py — webhook dispatch + slash commands."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.config import Config
from moment.core.discord_bot import (
    AUTO_START_AUTO,
    AUTO_START_AUTO_DELAYED,
    AUTO_START_DISABLED,
    AUTO_START_MANUAL,
    DiscordBot,
    _fmt_duration,
    _fmt_size,
    _status_emoji,
    _DISCORD_AVAILABLE,
)
from moment.core.models import Clip, ClipStatus, Webhook


@pytest.fixture
def config(db_path):
    """Return a Config backed by a temp DB."""
    cfg = Config(db_path=db_path)
    cfg.set("discord_bot_token", "fake-token-123")
    return cfg


@pytest.fixture
def bot(store, config):
    """Return a DiscordBot instance."""
    return DiscordBot(store, config)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


class TestImportWithoutDiscord:
    def test_module_imports_cleanly_without_discord(self):
        """Verify the module is importable when discord.py is absent.

        Since discord.py is genuinely absent in this test environment,
        the module has already proven it imports cleanly.
        """
        # The module was imported at the top of this file without error.
        # _DISCORD_AVAILABLE reflects the real state.
        from moment.core.discord_bot import DiscordBot
        assert DiscordBot is not None
        # Verify the bot reports unavailability correctly
        assert DiscordBot.is_available.fget(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_fmt_duration(self):
        assert _fmt_duration(65.5) == "1:05"
        assert _fmt_duration(0) == "0:00"
        assert _fmt_duration(3600) == "60:00"

    def test_fmt_size(self):
        assert _fmt_size(500) == "500 B"
        assert _fmt_size(2048) == "2.0 KB"
        assert _fmt_size(5_000_000) == "4.8 MB"

    def test_status_emoji(self):
        clip = Clip(id="x", stem="t", source_path=Path("/tmp/t.mkv"))
        clip.status = ClipStatus.UPLOADED
        assert _status_emoji(clip) == "✅"
        clip.status = ClipStatus.ERROR
        assert _status_emoji(clip) == "❌"
        clip.status = ClipStatus.PENDING
        assert _status_emoji(clip) == "⏳"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_is_available_property(self, bot):
        assert isinstance(bot.is_available, bool)

    def test_is_running_initially_false(self, bot):
        assert not bot.is_running

    def test_start_no_token(self, store, db_path):
        """start() should be a no-op when no token is configured."""
        cfg = Config(db_path=db_path)
        bot = DiscordBot(store, cfg)
        bot.start()
        assert not bot.is_running

    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", False)
    def test_start_when_unavailable(self, bot):
        bot.start()
        assert not bot.is_running

    def test_auto_start_disabled(self, bot):
        bot._auto_start_mode = AUTO_START_DISABLED
        bot.auto_start()
        assert not bot.is_running

    def test_auto_start_manual(self, bot):
        bot._auto_start_mode = AUTO_START_MANUAL
        bot.auto_start()
        assert not bot.is_running

    def test_stop_when_not_running_is_noop(self, bot):
        # Should not raise
        bot.stop()


# ---------------------------------------------------------------------------
# Auto-start modes
# ---------------------------------------------------------------------------


class TestAutoStart:
    def test_config_reads_auto_start_mode(self, store, db_path):
        cfg = Config(db_path=db_path)
        cfg.set("discord_bot_auto_start", AUTO_START_AUTO)
        bot = DiscordBot(store, cfg)
        assert bot.auto_start_mode == AUTO_START_AUTO

    def test_default_auto_start_is_disabled(self, store, db_path):
        cfg = Config(db_path=db_path)
        bot = DiscordBot(store, cfg)
        assert bot.auto_start_mode == AUTO_START_DISABLED


# ---------------------------------------------------------------------------
# Webhook dispatch
# ---------------------------------------------------------------------------

class TestWebhookDispatch:
    def test_send_disabled_webhook(self, bot):
        clip = Clip(id="c1", stem="t1", source_path=Path("/tmp/t1.mkv"))
        wh = Webhook(id="w1", url="https://discord.com/api/webhooks/1", enabled=False)
        result = bot.send_webhook(clip, wh)
        assert result is False

    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", False)
    def test_send_when_unavailable(self, bot):
        clip = Clip(id="c1", stem="t1", source_path=Path("/tmp/t1.mkv"))
        wh = Webhook(id="w1", url="https://discord.com/api/webhooks/1")
        result = bot.send_webhook(clip, wh)
        assert result is False

    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", True)
    @patch("moment.core.discord_bot.discord", create=True)
    def test_send_webhook_success(self, mock_discord, bot):
        mock_webhook = MagicMock()
        mock_discord.SyncWebhook.from_url.return_value = mock_webhook

        clip = Clip(
            id="c1", stem="t1", source_path=Path("/tmp/t1.mkv"),
            title="Epic Shot", game="cs2", duration=15.0, file_size=5_000_000,
        )
        wh = Webhook(id="w1", url="https://discord.com/api/webhooks/1", name="Main")
        result = bot.send_webhook(clip, wh)
        assert result is True
        mock_discord.SyncWebhook.from_url.assert_called_once_with("https://discord.com/api/webhooks/1")
        mock_webhook.send.assert_called_once()

    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", True)
    @patch("moment.core.discord_bot.discord", create=True)
    def test_send_webhook_failure(self, mock_discord, bot):
        mock_discord.SyncWebhook.from_url.side_effect = RuntimeError("Network error")

        clip = Clip(id="c1", stem="t1", source_path=Path("/tmp/t1.mkv"))
        wh = Webhook(id="w1", url="https://discord.com/api/webhooks/1")
        result = bot.send_webhook(clip, wh)
        assert result is False


# ---------------------------------------------------------------------------
# Embed builder (conditional on discord.py)
# ---------------------------------------------------------------------------

class TestEmbed:
    def test_build_clip_embed_not_available(self):
        """When discord.py is not available, _build_clip_embed returns None."""
        from moment.core.discord_bot import _build_clip_embed
        clip = Clip(id="x", stem="t", source_path=Path("/tmp/t.mkv"))
        result = _build_clip_embed(clip)
        # When discord.py is not installed, returns None
        if not _DISCORD_AVAILABLE:
            assert result is None


# ---------------------------------------------------------------------------
# Thread safety — double-start
# ---------------------------------------------------------------------------

class TestThreadSafety:
    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", True)
    @patch("moment.core.discord_bot.threading.Thread")
    def test_double_start_is_noop(self, mock_thread, bot):
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        bot.start()
        assert bot.is_running

        # Second start should warn but not crash
        bot.start()
        assert bot.is_running
        # Thread should only be created once
        assert mock_thread.call_count == 1
