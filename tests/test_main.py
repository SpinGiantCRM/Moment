"""Tests for main.py — CLI entry point and subcommand dispatch."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from moment.main import main


class TestMainDispatch:
    """Tests for the main() entry point dispatch logic."""

    def test_no_args_launches_gui(self) -> None:
        with (
            patch.object(sys, "argv", ["moment"]),
            patch("moment.ui.app.main") as mock_gui,
        ):
            main()
            mock_gui.assert_called_once()

    def test_bot_subcommand(self) -> None:
        with (
            patch.object(sys, "argv", ["moment", "bot"]),
            patch("moment.bot.main.run_bot", return_value=0) as mock_run_bot,
        ):
            with pytest.raises(SystemExit):
                main()
            mock_run_bot.assert_called_once()

    def test_mcp_subcommand(self) -> None:
        with (
            patch.object(sys, "argv", ["moment", "mcp"]),
            patch("moment.mcp.main.run_mcp", return_value=0) as mock_run_mcp,
        ):
            with pytest.raises(SystemExit):
                main()
            mock_run_mcp.assert_called_once()

    def test_bot_subcommand_with_args(self) -> None:
        with (
            patch.object(sys, "argv", ["moment", "bot", "--daemon"]),
            patch("moment.bot.main.run_bot", return_value=0) as mock_run_bot,
        ):
            with pytest.raises(SystemExit):
                main()
            mock_run_bot.assert_called_once()


class TestMainModule:
    """Test the __main__ module is importable."""

    def test_main_importable(self) -> None:
        from moment.__main__ import main as entry_main

        assert callable(entry_main)


class TestMainEdgeCases:
    """Edge cases for main module."""

    def test_empty_argv_after_program_name(self) -> None:
        with (
            patch.object(sys, "argv", ["moment"]),
            patch("moment.ui.app.main") as mock_gui,
        ):
            main()
            mock_gui.assert_called_once()

    def test_bot_with_no_additional_args(self) -> None:
        with (
            patch.object(sys, "argv", ["moment", "bot"]),
            patch("moment.bot.main.run_bot", return_value=0) as mock_run_bot,
        ):
            with pytest.raises(SystemExit):
                main()
            mock_run_bot.assert_called_once()

    def test_unknown_subcommand_falls_to_gui(self) -> None:
        """Anything not 'bot' or 'mcp' defaults to GUI."""
        with (
            patch.object(sys, "argv", ["moment", "unknown"]),
            patch("moment.ui.app.main") as mock_gui,
        ):
            main()
            mock_gui.assert_called_once()
