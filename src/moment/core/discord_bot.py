"""Discord bot — webhook dispatch + slash commands via discord.py.

Uses :mod:`discord.py` as an **optional dependency**.  If the package is
not installed the module still imports cleanly — all public methods become
no-ops that log a warning.

The bot runs in its own thread so it never blocks the Qt event loop.

Absolutely **no GUI imports** allowed in this module.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from moment.core.config import Config
from moment.core.models import Clip, ClipStatus, Webhook
from moment.core.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import discord
    from discord import app_commands

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False
    logger.info("discord.py not installed — Discord bot features disabled")


# Auto-start modes
AUTO_START_DISABLED = "disabled"
AUTO_START_AUTO = "auto"
AUTO_START_AUTO_DELAYED = "auto-delayed"
AUTO_START_MANUAL = "manual"

_AUTO_START_DELAY_SECONDS = 30


# ---------------------------------------------------------------------------
# Pure helpers — always available
# ---------------------------------------------------------------------------


def _status_emoji(clip: Clip) -> str:
    return {
        ClipStatus.UPLOADED: "✅",
        ClipStatus.ENCODING: "🔄",
        ClipStatus.UPLOADING: "⬆️",
        ClipStatus.DONE: "✔️",
        ClipStatus.ERROR: "❌",
        ClipStatus.CORRUPT: "💥",
    }.get(clip.status, "⏳")


def _fmt_duration(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _fmt_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}" if unit != "B" else f"{n_bytes} B"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Discord-dependent code — only defined when the package is available
# ---------------------------------------------------------------------------

if _DISCORD_AVAILABLE:

    class _ClipBotClient(discord.Client):
        """discord.py Client subclass with slash commands for clip queries."""

        def __init__(
            self, store: Store, *, intents: discord.Intents | None = None
        ) -> None:
            intents = intents or discord.Intents.default()
            super().__init__(intents=intents)
            self._store = store
            self._tree = app_commands.CommandTree(self)

        async def setup_hook(self) -> None:
            """Register slash commands on guild connect."""
            self._tree.add_command(_recent_command(self._store))
            self._tree.add_command(_stats_command(self._store))
            self._tree.add_command(_search_command(self._store))
            self._tree.add_command(_clip_command(self._store))

        async def on_ready(self) -> None:
            """Log when the bot successfully connects."""
            logger.info(
                "Discord bot ready — logged in as %s (id=%s)",
                self.user,
                self.user.id if self.user else "?",
            )
            try:
                synced = await self._tree.sync()
                logger.info("Synced %d slash commands", len(synced))
            except Exception:
                logger.exception("Failed to sync slash commands")

    # -- Slash command factories ---------------------------------------------

    def _recent_command(store: Store) -> app_commands.Command:
        @app_commands.describe(limit="Number of clips to show (1-25)")
        async def recent(interaction: discord.Interaction, limit: int = 5) -> None:
            """Show your most recent clips."""
            limit = max(1, min(25, limit))
            clips = store.list_clips(limit=limit, sort_by="-created_at")
            if not clips:
                await interaction.response.send_message(
                    "📭 No clips yet!", ephemeral=True
                )
                return

            lines: list[str] = [f"**Last {len(clips)} clip(s):**"]
            for i, clip in enumerate(clips, 1):
                si = _status_emoji(clip)
                name = clip.title or clip.stem
                url_part = f"  —  [🔗]({clip.r2_url})" if clip.r2_url else ""
                lines.append(
                    f"{i}. {si} **{name}**  ·  {_fmt_duration(clip.duration)}"
                    f"  ·  {clip.game or '—'}{url_part}"
                )
            await interaction.response.send_message("\n".join(lines))

        return app_commands.Command(
            name="recent",
            description="Show your most recent clips",
            callback=recent,
        )

    def _stats_command(store: Store) -> app_commands.Command:
        async def stats(interaction: discord.Interaction) -> None:
            """Show your clip library statistics."""
            total = store.count_clips()
            uploaded = store.count_clips(status=ClipStatus.UPLOADED)
            encoding = store.count_clips(status=ClipStatus.ENCODING)

            lines = [
                "**📊 Clip Library Stats**",
                f"Total clips: **{total}**",
                f"Uploaded to cloud: **{uploaded}**",
                f"Currently encoding: **{encoding}**",
            ]

            # Total storage used by clips
            all_clips = store.list_clips(limit=1000)
            total_bytes = sum(c.file_size for c in all_clips)
            lines.append(f"Storage used: **{_fmt_size(total_bytes)}**")

            await interaction.response.send_message("\n".join(lines))

        return app_commands.Command(
            name="stats",
            description="Show clip library statistics",
            callback=stats,
        )

    def _search_command(store: Store) -> app_commands.Command:
        @app_commands.describe(
            query="Text to search in clip titles",
            game="Filter by game name",
            tag="Filter by tag",
        )
        async def search(
            interaction: discord.Interaction,
            query: str | None = None,
            game: str | None = None,
            tag: str | None = None,
        ) -> None:
            """Search for clips by title, game, or tag."""
            clips = store.list_clips(search=query, game=game, tag=tag, limit=10)
            if not clips:
                await interaction.response.send_message(
                    "🔍 No clips found.", ephemeral=True
                )
                return

            lines = [f"**🔍 Found {len(clips)} clip(s):**"]
            for i, clip in enumerate(clips, 1):
                url_part = f"  —  [🔗]({clip.r2_url})" if clip.r2_url else ""
                lines.append(
                    f"{i}. **{clip.title or clip.stem}**  ·  "
                    f"{_fmt_duration(clip.duration)}  ·  "
                    f"{clip.game or '—'}{url_part}"
                )
            await interaction.response.send_message("\n".join(lines))

        return app_commands.Command(
            name="search",
            description="Search clips by title, game, or tag",
            callback=search,
        )

    def _clip_command(store: Store) -> app_commands.Command:
        @app_commands.describe(clip_id="The clip ID (or first few characters)")
        async def clip_detail(
            interaction: discord.Interaction, clip_id: str
        ) -> None:
            """Get full details for a specific clip."""
            clip = store.get_clip(clip_id)
            if clip is None:
                # Try prefix match
                clips = store.list_clips(limit=20)
                for c in clips:
                    if c.id.startswith(clip_id):
                        clip = c
                        break

            if clip is None:
                await interaction.response.send_message(
                    f"❌ Clip `{clip_id}` not found.", ephemeral=True
                )
                return

            embed = _build_clip_embed(clip)
            await interaction.response.send_message(embed=embed)

        return app_commands.Command(
            name="clip",
            description="Get full details for a specific clip",
            callback=clip_detail,
        )

    def _build_clip_embed(clip: Clip) -> discord.Embed:
        embed = discord.Embed(
            title=clip.title or clip.stem,
            color=discord.Color.blurple(),
            timestamp=clip.created_at,
        )
        embed.add_field(name="Game", value=clip.game or "—", inline=True)
        embed.add_field(name="Duration", value=_fmt_duration(clip.duration), inline=True)
        embed.add_field(name="Size", value=_fmt_size(clip.file_size), inline=True)
        embed.add_field(name="Status", value=clip.status.name, inline=True)
        embed.add_field(
            name="Resolution",
            value=f"{clip.resolution[0]}×{clip.resolution[1]}",
            inline=True,
        )
        embed.add_field(name="FPS", value=str(clip.fps), inline=True)
        if clip.r2_url:
            embed.add_field(name="URL", value=clip.r2_url, inline=False)
        if clip.tags:
            embed.set_footer(text="Tags: " + ", ".join(clip.tags))
        return embed

else:
    # Stubs — keep the module importable when discord.py is absent
    _ClipBotClient: type | None = None
    _recent_command = None  # type: ignore[assignment]
    _stats_command = None  # type: ignore[assignment]
    _search_command = None  # type: ignore[assignment]
    _clip_command = None  # type: ignore[assignment]

    def _build_clip_embed(clip: Clip) -> None:
        return None


# ---------------------------------------------------------------------------
# DiscordBot — main public API
# ---------------------------------------------------------------------------


class DiscordBot:
    """Manages a discord.py bot lifecycle in a dedicated thread.

    All methods are safe to call regardless of whether ``discord.py`` is
    installed — they become graceful no-ops when the dependency is missing.
    """

    def __init__(self, store: Store, config: Config) -> None:
        self._store = store
        self._config = config
        self._client: discord.Client | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._auto_start_mode: str = config.get(
            "discord_bot_auto_start", AUTO_START_DISABLED
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """``True`` if discord.py is installed and the bot can be used."""
        return _DISCORD_AVAILABLE

    @property
    def is_running(self) -> bool:
        """``True`` if the bot is currently connected to Discord."""
        return self._running

    @property
    def auto_start_mode(self) -> str:
        """The configured auto-start mode (``disabled``, ``auto``, ``auto-delayed``, ``manual``)."""
        return self._auto_start_mode

    def start(self) -> None:
        """Start the bot in a background thread.

        No-op if discord.py is not installed or the bot is already running.
        """
        if not _DISCORD_AVAILABLE:
            logger.warning("Cannot start Discord bot — discord.py not installed")
            return
        if self._running:
            logger.warning("Discord bot already running")
            return

        token = self._config.get("discord_bot_token", "")
        if not token:
            logger.warning("Cannot start Discord bot — no token configured")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_async_loop,
            args=(token,),
            daemon=True,
            name="discord-bot",
        )
        self._thread.start()
        logger.info("Discord bot thread started")

    def stop(self) -> None:
        """Gracefully shut down the bot.

        No-op if the bot is not running.
        """
        if not self._running or self._client is None or self._loop is None:
            return

        logger.info("Stopping Discord bot …")
        try:
            asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
        except Exception:
            logger.exception("Error closing Discord client")

        if self._thread is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("Discord bot thread did not exit cleanly in 10s")
        self._running = False
        self._client = None
        self._loop = None
        logger.info("Discord bot stopped")

    def auto_start(self) -> None:
        """Start the bot if the configured auto-start mode allows it."""
        mode = self._auto_start_mode
        if mode in (AUTO_START_DISABLED, AUTO_START_MANUAL):
            return

        if mode == AUTO_START_AUTO_DELAYED:
            logger.info(
                "Discord bot auto-start delayed (%ds)", _AUTO_START_DELAY_SECONDS
            )
            timer = threading.Timer(_AUTO_START_DELAY_SECONDS, self.start)
            timer.daemon = True
            timer.start()
        else:
            self.start()

    # ------------------------------------------------------------------
    # Webhook dispatch
    # ------------------------------------------------------------------

    def send_webhook(self, clip: Clip, webhook: Webhook) -> bool:
        """Post a clip notification to a Discord channel via webhook.

        Uses discord.py's ``SyncWebhook`` for richer embeds (not raw HTTP).

        Args:
            clip: The clip to notify about.
            webhook: The webhook configuration.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        if not _DISCORD_AVAILABLE:
            logger.warning("Cannot send webhook — discord.py not installed")
            return False

        if not webhook.enabled:
            logger.debug("Webhook %s disabled — skipping", webhook.name)
            return False

        try:
            sync_webhook = discord.SyncWebhook.from_url(webhook.url)

            embed = discord.Embed(
                title=clip.title or clip.stem,
                description=f"New clip captured in **{clip.game or 'Unknown'}**",
                color=discord.Color.green(),
                timestamp=clip.created_at,
            )
            embed.add_field(
                name="Duration", value=_fmt_duration(clip.duration), inline=True
            )
            embed.add_field(
                name="Size", value=_fmt_size(clip.file_size), inline=True
            )
            if clip.r2_url:
                embed.add_field(name="Link", value=clip.r2_url, inline=False)
            if clip.tags:
                embed.set_footer(text="Tags: " + ", ".join(clip.tags))

            sync_webhook.send(
                content=f"🎬 **New clip:** {clip.title or clip.stem}",
                embed=embed,
                username="Moment",
                wait=False,
            )
            logger.info("Webhook sent: %s → %s", clip.stem, webhook.name)
            return True
        except Exception:
            logger.exception("Webhook dispatch failed for %s", webhook.name)
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_async_loop(self, token: str) -> None:
        """Run the asyncio event loop with the discord client in this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._client = _ClipBotClient(self._store)
            self._loop.run_until_complete(self._client.start(token))
        except discord.LoginFailure:
            logger.error("Discord bot login failed — invalid token")
        except Exception:
            logger.exception("Discord bot crashed")
        finally:
            self._running = False
            self._client = None
            self._loop.close()
            self._loop = None
