"""Tests for moment.bot.main — bot CLI entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestParser:
    def test_build_parser(self):
        from moment.bot.main import _build_parser

        parser = _build_parser()
        assert parser.prog == "moment bot"

    def test_parser_defaults(self):
        from moment.bot.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args([])
        assert args.daemon is False

    def test_parser_daemon(self):
        from moment.bot.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--daemon"])
        assert args.daemon is True


class TestRunBot:
    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", False)
    def test_returns_1_when_unavailable(self):
        from moment.bot.main import run_bot

        result = run_bot([])
        assert result == 1

    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", True)
    @patch("moment.bot.main._get_discord_token")
    @patch("moment.bot.main.Config")
    @patch("moment.bot.main.Store")
    def test_returns_1_when_no_token(self, mock_store_cls, mock_config_cls, mock_token):
        mock_token.return_value = ""
        mock_config_cls.return_value = MagicMock()
        mock_store_cls.return_value = MagicMock()

        from moment.bot.main import run_bot

        result = run_bot([])
        assert result == 1

    @patch("moment.core.discord_bot.DiscordBot")
    @patch("moment.bot.main._get_discord_token")
    @patch("moment.bot.main.Store")
    @patch("moment.bot.main.Config")
    @patch("moment.core.discord_bot._DISCORD_AVAILABLE", True)
    def test_daemon_mode(self, mock_config_cls, mock_store_cls, mock_token, mock_bot_cls):
        mock_token.return_value = "test-token"
        mock_config_cls.return_value = MagicMock()
        mock_store_cls.return_value = MagicMock()
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot

        from moment.bot.main import run_bot

        result = run_bot(["--daemon"])
        assert result == 0
        mock_bot.start.assert_called_once()
