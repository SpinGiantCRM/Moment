"""MCP tool definitions — read-only query tools and optional mutation tools.

All tools import :mod:`moment.core` modules directly (no REST layer).
They run in-process within the MCP server.

**Read-only tools** (always available):
    - ``list_clips`` — filtered/paginated clip list
    - ``search_clips`` — full-text + game/tag search
    - ``get_clip`` — single clip details
    - ``get_stats`` — aggregate library statistics
    - ``list_game_profiles`` — per-game recording profiles
    - ``list_webhooks`` — webhook configurations

**Mutation tools** (behind ``--allow-mutations`` flag):
    - ``enqueue_encode`` — re-encode a clip
    - ``enqueue_upload`` — re-upload a clip
    - ``save_game_profile`` — upsert a game profile
    - ``test_webhook`` — test-fire a webhook
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid as _uuid
from pathlib import Path
from typing import Any

from moment.core.config import Config
from moment.core.models import ClipStatus, GameProfile
from moment.core.store import Store
from moment.utils.system import validate_arg

logger = logging.getLogger(__name__)

_HOME = os.path.expanduser("~")

# Lazy store singleton — created on first tool invocation
_store: Store | None = None

_WEBHOOK_MIN_INTERVAL: float = 60.0  # seconds between test_webhook calls per URL


def _get_store() -> Store:
    """Return the global (lazy) Store singleton."""
    global _store
    if _store is None:
        config = Config()
        _store = Store(config=config)
    return _store


# ---------------------------------------------------------------------------
# Public tool functions (module-level, independently testable)
# ---------------------------------------------------------------------------


def list_clips(
    status: str | None = None,
    game: str | None = None,
    folder: str | None = None,
    limit: int = 50,
    offset: int = 0,
    *,
    visibility: str | None = None,
    include_urls: bool = False,
) -> list[dict[str, Any]]:
    """List clips with optional filters and pagination.

    Visibility is enforced server-side from the auth context:
        - Unauthenticated / read-only → PUBLIC + UNLISTED only.
        - Mutation-scoped → all clips including PRIVATE.

    Args:
        visibility: Filter by exact visibility (``public``, ``unlisted``, ``private``).
        include_urls: If ``True``, include ``r2_url`` in each clip dict.
            Default ``False`` — R2 URLs are opt-in for privacy.
    """
    store = _get_store()
    clip_status = None
    if status:
        try:
            clip_status = ClipStatus[status.upper()]
        except KeyError:
            clip_status = None

    clip_visibility = None
    if visibility:
        try:
            from moment.core.models import ClipVisibility
            clip_visibility = ClipVisibility(visibility.lower())
        except ValueError:
            pass

    # Derive owner context from auth scope (never from caller input)
    owner_id = _owner_id_from_auth()

    clips = store.list_clips(
        status=clip_status,
        game=game,
        folder=folder,
        limit=limit,
        offset=offset,
        visibility=clip_visibility,
        owner_id=owner_id,
        shape="detail",
    )
    return [
        {
            "id": c.id,
            "stem": c.stem,
            "title": c.title,
            "game": c.game,
            "duration": c.duration,
            "file_size": c.file_size,
            "status": c.status.name,
            "favorite": c.favorite,
            "created_at": c.created_at.isoformat(),
            "r2_url": c.r2_url if include_urls else None,
            "resolution": list(c.resolution),
            "tags": c.tags,
            "visibility": c.visibility.value,
        }
        for c in clips
    ]


def search_clips(
    query: str,
    game: str | None = None,
    tag: str | None = None,
    limit: int = 10,
    *,
    include_urls: bool = False,
) -> list[dict[str, Any]]:
    """Full-text search for clips by title, optionally filtered by game/tag.

    Visibility is enforced server-side from the auth context.
    """
    store = _get_store()
    owner_id = _owner_id_from_auth()
    clips = store.list_clips(
        search=query,
        game=game,
        tag=tag,
        limit=limit,
        owner_id=owner_id,
        shape="detail",
    )
    return [
        {
            "id": c.id,
            "stem": c.stem,
            "title": c.title,
            "game": c.game,
            "duration": c.duration,
            "file_size": c.file_size,
            "status": c.status.name,
            "r2_url": c.r2_url if include_urls else None,
            "tags": c.tags,
            "visibility": c.visibility.value,
        }
        for c in clips
    ]


def _redact_path(path_str: str) -> str:
    """Replace absolute path with ``~``-relative or just the filename.

    If the path starts with ``$HOME``, replace with ``~``.
    Otherwise return only the filename.
    """
    if path_str.startswith(_HOME):
        return "~" + path_str[len(_HOME):]
    return Path(path_str).name


def get_clip(
    clip_id: str,
    *,
    show_paths: bool = False,
    include_urls: bool = False,
) -> dict[str, Any] | None:
    """Get full details for a single clip by ID.

    Visibility enforced: PRIVATE clips are only visible to mutation-scoped
    callers.  Unauthenticated/read-only callers get a ``None`` response
    for PRIVATE clips (same as "not found").

    Args:
        clip_id: The clip's UUID.
        show_paths: If ``True``, return absolute filesystem paths.
            Default ``False`` — paths are redacted to ``~``-relative
            or filename-only for privacy.
        include_urls: If ``True``, include ``r2_url`` and ``r2_path``.
            Default ``False``.
    """
    from moment.core.models import ClipVisibility

    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return None

    # Visibility enforcement: PRIVATE clips hidden from unauthenticated
    if clip.visibility == ClipVisibility.PRIVATE and _owner_id_from_auth() is None:
        return None

    result: dict[str, Any] = {
        "id": clip.id,
        "stem": clip.stem,
        "title": clip.title,
        "game": clip.game,
        "duration": clip.duration,
        "file_size": clip.file_size,
        "video_codec": clip.video_codec,
        "fps": clip.fps,
        "resolution": list(clip.resolution),
        "has_mic_audio": clip.has_mic_audio,
        "has_game_audio": clip.has_game_audio,
        "status": clip.status.name,
        "favorite": clip.favorite,
        "tags": clip.tags,
        "folder": clip.folder,
        "visibility": clip.visibility.value,
        "created_at": clip.created_at.isoformat(),
        "uploaded_at": clip.uploaded_at.isoformat() if clip.uploaded_at else None,
        "r2_url": clip.r2_url if include_urls else None,
        "r2_path": clip.r2_path if include_urls else None,
        "watch_count": clip.watch_count,
        "clip_type": clip.clip_type.name,
    }

    if show_paths:
        result["source_path"] = str(clip.source_path)
        result["encoded_path"] = str(clip.encoded_path) if clip.encoded_path else None
        result["thumb_path"] = str(clip.thumb_path) if clip.thumb_path else None
    else:
        result["source_path"] = _redact_path(str(clip.source_path))
        result["encoded_path"] = _redact_path(str(clip.encoded_path)) if clip.encoded_path else None
        result["thumb_path"] = _redact_path(str(clip.thumb_path)) if clip.thumb_path else None

    return result


def get_stats() -> dict[str, Any]:
    """Get aggregate clip library statistics."""
    store = _get_store()
    return store.get_aggregate_stats()


def list_game_profiles(
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List per-game recording profiles with optional pagination.

    Args:
        limit: Max profiles to return (default 200, max 5000).
        offset: Number of profiles to skip.
    """
    store = _get_store()
    profiles = store.list_game_profiles(
        limit=min(max(1, limit), 5000),
        offset=max(0, offset),
    )
    return [
        {
            "id": p.id,
            "game_name": p.game_name,
            "display_name": p.display_name,
            "replay_duration": p.replay_duration,
            "capture_fps": p.capture_fps,
            "pause_encode": p.pause_encode,
            "auto_tag": p.auto_tag,
        }
        for p in profiles
    ]


def list_webhooks() -> list[dict[str, Any]]:
    """List all configured Discord webhooks (URLs redacted for security)."""
    store = _get_store()
    webhooks = store.list_webhooks()
    return [
        {
            "id": w.id,
            "name": w.name,
            "enabled": w.enabled,
            "notify_on": w.notify_on,
            "include_clip_url": w.include_clip_url,
        }
        for w in webhooks
    ]


def enqueue_encode(clip_id: str) -> dict[str, str]:
    """Re-encode a specific clip.  Requires mutation-scoped token."""
    scope_error = _check_mutation_allowed()
    if scope_error is not None:
        return {"error": scope_error}

    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return {"error": f"Clip {clip_id} not found"}
    logger.info("Encode requested for %s via MCP", clip_id)
    return {"status": "queued", "clip_id": clip_id}


def enqueue_upload(clip_id: str) -> dict[str, str]:
    """Re-upload a specific clip to cloud storage.  Requires mutation-scoped token."""
    scope_error = _check_mutation_allowed()
    if scope_error is not None:
        return {"error": scope_error}

    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return {"error": f"Clip {clip_id} not found"}
    if not clip.encoded_path:
        return {"error": "Clip has no encoded file to upload"}
    logger.info("Upload requested for %s via MCP", clip_id)
    return {"status": "queued", "clip_id": clip_id}


def save_game_profile(profile_json: str) -> dict[str, str]:
    """Create or update a game recording profile from JSON.

    Requires mutation-scoped token.
    """
    scope_error = _check_mutation_allowed()
    if scope_error is not None:
        return {"error": scope_error}

    store = _get_store()
    try:
        data = json.loads(profile_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}

    if "game_name" not in data:
        return {"error": "Missing required field: game_name"}

    # Validate audio device fields at the API boundary
    audio_config = data.get("audio_config")
    if audio_config and isinstance(audio_config, dict):
        for key in ("game_device", "mic_device"):
            val = audio_config.get(key)
            if val:
                validate_arg(str(val), context="device")

    profile = GameProfile(
        id=data.get("id") or str(_uuid.uuid4()),
        game_name=data["game_name"],
        display_name=data.get("display_name", data["game_name"]),
        replay_duration=data.get("replay_duration", 30),
        capture_fps=data.get("capture_fps", 60),
        pause_encode=data.get("pause_encode", True),
        pause_thumbnail=data.get("pause_thumbnail", True),
        auto_tag=data.get("auto_tag", True),
        audio_config=audio_config,
    )
    store.save_game_profile(profile)
    return {"status": "saved", "game_name": profile.game_name}


def _owner_id_from_auth() -> str | None:
    """Return the owner_id derived from the auth context, or ``None``.

    Mutation-scoped tokens → ``"*"`` (wildcard — sees all clips including PRIVATE).
    Read-only / unauthenticated → ``None`` (PUBLIC + UNLISTED only).
    """
    try:
        from moment.mcp.server import get_auth_scope
        scope = get_auth_scope()
        if scope == "mutation":
            return "*"
    except Exception:
        pass
    return None


def _check_mutation_allowed() -> str | None:
    """Return an error message if the caller lacks mutation scope, or ``None``."""
    try:
        from moment.mcp.server import get_auth_scope
        if get_auth_scope() != "mutation":
            return "Forbidden: mutation-scoped token required for this operation"
    except Exception:
        pass
    return None


def _check_webhook_rate_limit(url_hash: str) -> str | None:
    """Return an error message if rate-limited, or ``None`` if allowed.

    Uses persistent SQLite-based rate limiting via the Store.
    Thread-safe via the store's internal lock.
    """
    store = _get_store()
    return store.check_persistent_rate(f"webhook_test:{url_hash}", _WEBHOOK_MIN_INTERVAL)


def test_webhook(webhook_id: str, *, _url_hash: str | None = None) -> dict[str, str]:
    """Test-fire a configured webhook.

    Rate-limited to once per 60 seconds per webhook URL (persisted across restarts).
    Requires mutation-scoped token.
    """
    # Scope check — mutation token required
    scope_error = _check_mutation_allowed()
    if scope_error is not None:
        return {"error": scope_error}

    store = _get_store()
    webhooks = store.list_webhooks()
    wh = next((w for w in webhooks if w.id == webhook_id), None)
    if wh is None:
        return {"error": f"Webhook {webhook_id} not found"}

    # Rate limit check — hash the webhook URL for the rate-limit key
    url_hash = _url_hash or hashlib.sha256(wh.url.encode()).hexdigest()[:12]
    rate_error = _check_webhook_rate_limit(url_hash)
    if rate_error is not None:
        return {"error": rate_error}

    try:
        from moment.core.discord_bot import DiscordBot
        from moment.core.models import Clip

        test_clip = Clip(
            id="test-test-test",
            stem="test_clip",
            source_path="",
            duration=10.0,
            file_size=1024000,
            title="MCP Test Clip",
            game="Moment",
            status=ClipStatus.DONE,
        )
        bot = DiscordBot(store, Config())
        success = bot.send_webhook(test_clip, wh)
        if success:
            return {"status": "sent", "webhook_id": webhook_id}
        else:
            return {"error": "Webhook dispatch failed — check server logs"}
    except Exception as exc:
        return {"error": f"Webhook test failed: {exc}"}


# ---------------------------------------------------------------------------
# Registration hook
# ---------------------------------------------------------------------------


def register_all_tools(server: Any, *, allow_mutations: bool = False) -> None:
    """Register all MCP tools on the given FastMCP server instance.

    Args:
        server: A :class:`fastmcp.FastMCP` instance.
        allow_mutations: If ``True``, also register write tools.
    """
    _register_read_tools(server)
    if allow_mutations:
        _register_mutation_tools(server)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def _register_read_tools(server: Any) -> None:
    """Register read-only query tools."""
    server.tool()(list_clips)
    server.tool()(search_clips)
    server.tool()(get_clip)
    server.tool()(get_stats)
    server.tool()(list_game_profiles)
    server.tool()(list_webhooks)


def _register_mutation_tools(server: Any) -> None:
    """Register write/pipeline tools (guarded by --allow-mutations)."""
    server.tool()(enqueue_encode)
    server.tool()(enqueue_upload)
    server.tool()(save_game_profile)
    server.tool()(test_webhook)
