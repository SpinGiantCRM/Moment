"""Application bootstrap — CLI entry point for Moment.

Usage::

    moment             launch the GUI (default)
    moment --version   print version and exit
    moment bot         start the Discord bot
    moment mcp         start the MCP server
"""

from __future__ import annotations

import sys


def main() -> None:
    """Main entry point — dispatch to subcommand or start GUI."""
    argv = sys.argv[1:]

    # --version / --help (without loading Qt)
    if "--version" in argv:
        from moment import __version__

        print(f"moment {__version__}")
        sys.exit(0)

    if "--help" in argv:
        print(__doc__.strip())
        sys.exit(0)

    # Subcommand dispatch
    if argv and argv[0] == "bot":
        from moment.bot.main import run_bot

        sys.exit(run_bot(argv[1:]))

    if argv and argv[0] == "mcp":
        from moment.mcp.main import run_mcp

        sys.exit(run_mcp(argv[1:]))

    # Default: launch GUI
    from moment.ui.app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
