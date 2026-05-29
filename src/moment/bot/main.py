"""CLI entry point for the ``moment bot`` subcommand.

Parses arguments, checks the optional dependency, wires up a
:class:`~moment.core.discord_bot.DiscordBot` instance, and blocks
until the bot exits.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from moment.core.config import Config
from moment.core.store import Store, set_store_config

logger = logging.getLogger(__name__)


def run_bot(argv: list[str] | None = None) -> int:
    """Parse args, start the Discord bot, and block until signalled.

    Returns 0 on success, 1 on error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Validate optional dependency
    from moment.core.discord_bot import _DISCORD_AVAILABLE as _available

    if not _available:
        print(
            "discord.py not installed.  Run:\n"
            "    pip install moment[bot]\n"
            "or  pip install discord.py",
            file=sys.stderr,
        )
        return 1

    # Bootstrap store + config (order matters: Config first, then inject into Store)
    config = Config()
    set_store_config(config)
    store = Store()

    # Token override
    if args.token:
        config.set("discord_bot_token", args.token.strip())

    # Check token exists
    token = config.get("discord_bot_token", "")
    if not token:
        print(
            "No bot token configured.\n"
            "Set one in Settings → Bot tab, or pass --token TOKEN.",
            file=sys.stderr,
        )
        return 1

    from moment.core.discord_bot import DiscordBot

    bot = DiscordBot(store, config)

    if args.daemon:
        # Daemon mode: the caller (e.g. tray) manages the lifecycle.
        # Just start and return immediately.
        bot.start()
        print(f"Discord bot started in daemon mode (PID={os.getpid()})")
        return 0

    # Foreground mode: start and block until SIGINT/SIGTERM
    bot.start()

    shutdown_flag: list[bool] = [False]

    def _on_signal(signum: int, frame: object) -> None:
        logger.info("Received signal %d, shutting down bot …", signum)
        shutdown_flag[0] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    print("Discord bot running. Press Ctrl-C to stop.")
    try:
        while not shutdown_flag[0] and bot.is_running:
            time.sleep(0.5)
    finally:
        bot.stop()
        store.close()

    print("Discord bot stopped.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moment bot",
        description="Start the Discord bot for clip queries.",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Start in background (for tray-managed lifecycle).",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        metavar="TOKEN",
        help="Discord bot token (overrides config DB).",
    )
    return parser
