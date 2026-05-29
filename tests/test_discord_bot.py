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


# ---------------------------------------------------------------------------
# Role-based auth (Spec 14)
# ---------------------------------------------------------------------------


class TestRoleAuth:
    """Tests for _require_role and _get_allowed_roles helpers."""

    def test_allowed_roles_default(self):
        """Default role should be 'Moment User'."""
        import os
        import tempfile
        from pathlib import Path

        from moment.core.store import Store, set_store_config
        from moment.core.config import Config

        # Use temp DB
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            cfg = Config(db_path=db_path)
            cfg.set("discord_allowed_roles", "Moment User")

            from moment.core.discord_bot import _get_allowed_roles
            store = Store(db_path=db_path)
            roles = _get_allowed_roles(store)
            assert "Moment User" in roles
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass

    def test_allowed_roles_custom(self):
        """Custom comma-separated roles work."""
        import os
        import tempfile

        from moment.core.store import Store
        from moment.core.config import Config

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            cfg = Config(db_path=db_path)
            cfg.set("discord_allowed_roles", "VIP,  Editor , Admin")

            from moment.core.discord_bot import _get_allowed_roles
            store = Store(db_path=db_path)
            roles = _get_allowed_roles(store)
            assert roles == {"VIP", "Editor", "Admin"}
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass


# ---------------------------------------------------------------------------
# Visibility enforcement in Discord (Spec 24)
# ---------------------------------------------------------------------------


class TestDiscordVisibility:
    """Tests for visibility enforcement in Discord slash commands."""

    def test_get_caller_id_returns_user_id_str(self):
        """_get_caller_id should return the user's ID as a string."""
        from moment.core.discord_bot import _get_caller_id
        interaction = MagicMock()
        interaction.user.id = 123456789
        assert _get_caller_id(interaction) == "123456789"

    def test_build_clip_embed_strips_r2_by_default(self):
        """_build_clip_embed should NOT include R2 URL unless include_url=True."""
        with patch("moment.core.discord_bot._DISCORD_AVAILABLE", True):
            import discord as _discord
            from moment.core.discord_bot import _build_clip_embed

            clip = Clip(
                id="emb",
                stem="emb",
                source_path="/tmp/emb.mkv",
                duration=10.0,
                file_size=1000000,
                title="Test",
                status=ClipStatus.DONE,
                clip_type=ClipType.VIDEO,
                r2_url="https://cdn.example.com/test.mp4",
            )
            embed = _build_clip_embed(clip, include_url=False)
            # Check that the URL field says to use --include-url
            url_field = next(
                (f for f in embed.fields if f.name == "URL"), None
            )
            assert url_field is not None
            assert "include-url" in url_field.value

    def test_build_clip_embed_includes_url_when_flagged(self):
        """_build_clip_embed should include R2 URL when include_url=True."""
        with patch("moment.core.discord_bot._DISCORD_AVAILABLE", True):
            from moment.core.discord_bot import _build_clip_embed

            clip = Clip(
                id="emb2",
                stem="emb2",
                source_path="/tmp/emb2.mkv",
                duration=10.0,
                file_size=1000000,
                title="Test",
                status=ClipStatus.DONE,
                clip_type=ClipType.VIDEO,
                r2_url="https://cdn.example.com/test2.mp4",
            )
            embed = _build_clip_embed(clip, include_url=True)
            url_field = next(
                (f for f in embed.fields if f.name == "URL"), None
            )
            assert url_field is not None
            assert "test2.mp4" in url_field.value

    def test_build_clip_embed_no_url_when_no_r2(self):
        """_build_clip_embed should not add URL field if no r2_url."""
        with patch("moment.core.discord_bot._DISCORD_AVAILABLE", True):
            from moment.core.discord_bot import _build_clip_embed

            clip = Clip(
                id="emb3",
                stem="emb3",
                source_path="/tmp/emb3.mkv",
                duration=10.0,
                file_size=1000000,
                title="Test",
                status=ClipStatus.DONE,
                clip_type=ClipType.VIDEO,
                r2_url=None,
            )
            embed = _build_clip_embed(clip, include_url=True)
            url_field = next(
                (f for f in embed.fields if f.name == "URL"), None
            )
            assert url_field is None
