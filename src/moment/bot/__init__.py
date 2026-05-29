"""Discord bot subcommand — ``moment bot``.

Thin CLI wrapper around :class:`moment.core.discord_bot.DiscordBot`.

Usage::

    moment bot              # foreground
    moment bot --daemon     # background (tray-managed)

Token is read from ``MOMENT_DISCORD_TOKEN`` env var or system keyring.
"""

from __future__ import annotations

from moment.bot.main import run_bot

__all__ = ["run_bot"]
