"""Discord bot subcommand — ``clip-tray bot``.

Thin CLI wrapper around :class:`clip_tray.core.discord_bot.DiscordBot`.
The bot runs as a foreground or daemon process and exposes slash commands
for querying the local clip library.

Usage::

    clip-tray bot              # foreground
    clip-tray bot --daemon     # background (tray-managed)
    clip-tray bot --token ...  # override token
"""

from __future__ import annotations

from clip_tray.bot.main import run_bot

__all__ = ["run_bot"]
