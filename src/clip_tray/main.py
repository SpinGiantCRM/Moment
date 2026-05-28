"""Application bootstrap — CLI entry point for clip-tray.

Supports subcommands::

    clip-tray           launch the GUI (default)
    clip-tray bot       start the Discord bot
    clip-tray mcp       start the MCP server
"""

from __future__ import annotations

import sys


def main() -> None:
    """Main entry point — dispatch to subcommand or start GUI."""
    argv = sys.argv[1:]

    # Subcommand dispatch
    if argv and argv[0] == "bot":
        from clip_tray.bot.main import run_bot

        sys.exit(run_bot(argv[1:]))

    if argv and argv[0] == "mcp":
        from clip_tray.mcp.main import run_mcp

        sys.exit(run_mcp(argv[1:]))

    # Default: launch GUI
    from clip_tray.ui.app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
