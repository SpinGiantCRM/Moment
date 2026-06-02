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
from typing import Any

from moment.core.config import Config
from moment.core.models import Clip, ClipStatus, ClipVisibility, Webhook
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
# Token retrieval — env var → keyring fallback
# ---------------------------------------------------------------------------


def _get_discord_token() -> str:
    """Return the Discord bot token from the system keyring only.

    The token is stored via ``keyring.get_password("moment",
    "discord_bot_token")``.  No environment-variable fallback is
    provided — env vars are readable by any same-user process.

    Returns:
        The token string, or ``""`` if keyring is unavailable or
        the token is not configured.
    """
    try:
        import keyring

        token = keyring.get_password("moment", "discord_bot_token") or ""
        if token:
            logger.debug("Discord token read from system keyring")
        return token
    except ImportError:
        logger.warning(
            "keyring not installed — Discord bot token unavailable. "
            "Install with: pip install keyring"
        )
        return ""
    except Exception:
        logger.warning("Failed to read Discord token from keyring", exc_info=True)
        return ""


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
    # -- Auth helpers ---------------------------------------------------------

    def _get_allowed_roles(store: Store) -> set[str]:
        """Return the set of role names allowed to use slash commands.

        Reads ``discord_allowed_roles`` from config (default ``"Moment User"``).
        """
        from moment.core.config import Config

        config = Config(db_path=store._db_path)
        raw = config.get("discord_allowed_roles", "Moment User")
        if isinstance(raw, str):
            return {r.strip() for r in raw.split(",") if r.strip()}
        return {"Moment User"}

    def _require_role(store: Store):
        """Decorator that checks the invoking user has an allowed role.

        Returns an ephemeral error if the user lacks permission.
        """

        def decorator(func):
            from functools import wraps

            @wraps(func)
            async def wrapper(interaction: discord.Interaction, *args, **kwargs):
                allowed = _get_allowed_roles(store)
                if not allowed:
                    # No roles configured → allow all (backward compat)
                    return await func(interaction, *args, **kwargs)

                user_roles = {r.name for r in getattr(interaction.user, "roles", [])}
                if not allowed & user_roles:
                    await interaction.response.send_message(
                        "❌ You don't have permission to use this command.",
                        ephemeral=True,
                    )
                    return
                return await func(interaction, *args, **kwargs)

            return wrapper

        return decorator

    def _get_caller_id(interaction: discord.Interaction) -> str:
        """Return the calling user's ID as a string for ownership checks."""
        return str(interaction.user.id) if interaction.user else ""

    class _ClipBotClient(discord.Client):
        """discord.py Client subclass with slash commands for clip queries."""

        def __init__(self, store: Store, *, intents: discord.Intents | None = None) -> None:
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
        @_require_role(store)
        async def recent(interaction: discord.Interaction, limit: int = 5) -> None:
            """Show recent PUBLIC clips."""
            limit = max(1, min(25, limit))
            clips = store.list_clips(
                limit=limit,
                sort_by="-created_at",
                visibility=ClipVisibility.PUBLIC,
            )
            if not clips:
                await interaction.response.send_message("📭 No clips yet!", ephemeral=True)
                return

            lines: list[str] = [f"**Last {len(clips)} clip(s):**"]
            for i, clip in enumerate(clips, 1):
                si = _status_emoji(clip)
                name = clip.title or clip.stem
                lines.append(
                    f"{i}. {si} **{name}**  ·  {_fmt_duration(clip.duration)}"
                    f"  ·  {clip.game or '—'}"
                )
            await interaction.response.send_message("\n".join(lines))

        return app_commands.Command(
            name="recent",
            description="Show recent public clips",
            callback=recent,
        )

    def _stats_command(store: Store) -> app_commands.Command:
        @_require_role(store)
        async def stats(interaction: discord.Interaction) -> None:
            """Show clip library statistics."""
            owner_id = _get_caller_id(interaction)
            total = store.count_clips()
            uploaded = store.count_clips(status=ClipStatus.UPLOADED)
            encoding = store.count_clips(status=ClipStatus.ENCODING)

            lines = [
                "**📊 Clip Library Stats**",
                f"Total clips: **{total}**",
                f"Uploaded to cloud: **{uploaded}**",
                f"Currently encoding: **{encoding}**",
            ]

            # Total storage used by clips (owner-scoped)
            all_clips = store.list_clips(limit=1000, owner_id=owner_id)
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
        @_require_role(store)
        async def search(
            interaction: discord.Interaction,
            query: str | None = None,
            game: str | None = None,
            tag: str | None = None,
        ) -> None:
            """Search for PUBLIC + UNLISTED clips by title, game, or tag."""
            owner_id = _get_caller_id(interaction)
            clips = store.list_clips(
                search=query,
                game=game,
                tag=tag,
                limit=10,
                owner_id=owner_id,
            )
            if not clips:
                await interaction.response.send_message("🔍 No clips found.", ephemeral=True)
                return

            lines = [f"**🔍 Found {len(clips)} clip(s):**"]
            for i, clip in enumerate(clips, 1):
                lines.append(
                    f"{i}. **{clip.title or clip.stem}**  ·  "
                    f"{_fmt_duration(clip.duration)}  ·  "
                    f"{clip.game or '—'}"
                )
            await interaction.response.send_message("\n".join(lines))

        return app_commands.Command(
            name="search",
            description="Search clips by title, game, or tag",
            callback=search,
        )

    def _clip_command(store: Store) -> app_commands.Command:
        @app_commands.describe(
            clip_id="The clip ID (exact match only)",
            include_url="Include the R2/cloud URL in the response",
        )
        @_require_role(store)
        async def clip_detail(
            interaction: discord.Interaction,
            clip_id: str,
            include_url: bool = False,
        ) -> None:
            """Get full details for a specific clip (exact ID match only).

            Visibility enforcement: PRIVATE clips only shown to the owner.
            """
            owner_id = _get_caller_id(interaction)
            clip = store.get_clip(clip_id)

            if clip is None:
                await interaction.response.send_message(
                    f"❌ Clip `{clip_id}` not found.", ephemeral=True
                )
                return

            # Visibility enforcement — deny by default when ownership is ambiguous
            if clip.visibility == ClipVisibility.PRIVATE and (
                not clip.discord_user_id or clip.discord_user_id != owner_id
            ):
                await interaction.response.send_message(
                    f"❌ Clip `{clip_id}` not found.", ephemeral=True
                )
                return

            embed = _build_clip_embed(clip, include_url=include_url)
            await interaction.response.send_message(embed=embed)

        return app_commands.Command(
            name="clip",
            description="Get full details for a specific clip",
            callback=clip_detail,
        )

    def _build_clip_embed(clip: Clip, *, include_url: bool = False) -> discord.Embed:
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
            if include_url:
                embed.add_field(name="URL", value=clip.r2_url, inline=False)
            else:
                embed.add_field(
                    name="URL",
                    value="Use `/clip <id> --include-url` for URL",
                    inline=False,
                )
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

    def _build_clip_embed(clip: Clip, *, include_url: bool = False) -> None:
        return None

    def _get_allowed_roles(store: Store) -> set[str]:
        return {"Moment User"}

    def _require_role(store: Store):
        def decorator(func):
            return func

        return decorator

    def _get_caller_id(interaction: Any = None) -> str:
        return ""


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
        self._auto_start_mode: str = config.get("discord_bot_auto_start", AUTO_START_DISABLED)

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

        token = _get_discord_token()
        if not token:
            logger.warning(
                "Cannot start Discord bot — no token configured. "
                "Run `keyring set moment discord_bot_token`"
            )
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
            logger.info("Discord bot auto-start delayed (%ds)", _AUTO_START_DELAY_SECONDS)
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
        The real webhook URL is decrypted from the store at dispatch time.

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

        # Decrypt the real URL from the store (redacted URLs are for display only)
        real_url = self._store.get_webhook_url(webhook.id)
        if real_url is None:
            logger.error("Webhook %s: failed to retrieve URL from store", webhook.name)
            return False

        try:
            sync_webhook = discord.SyncWebhook.from_url(real_url)

            embed = discord.Embed(
                title=clip.title or clip.stem,
                description=f"New clip captured in **{clip.game or 'Unknown'}**",
                color=discord.Color.green(),
                timestamp=clip.created_at,
            )
            embed.add_field(name="Duration", value=_fmt_duration(clip.duration), inline=True)
            embed.add_field(name="Size", value=_fmt_size(clip.file_size), inline=True)
            if clip.r2_url and webhook.include_clip_url:
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
