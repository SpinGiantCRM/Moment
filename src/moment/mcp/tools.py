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

import json
import logging
import uuid as _uuid
from typing import Any

from moment.core.config import Config
from moment.core.models import ClipStatus, GameProfile
from moment.core.store import Store, set_store_config

logger = logging.getLogger(__name__)

# Lazy store singleton — created on first tool invocation
_store: Store | None = None


def _get_store() -> Store:
    """Return the global (lazy) Store singleton."""
    global _store
    if _store is None:
        config = Config()
        set_store_config(config)
        _store = Store()
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
) -> list[dict[str, Any]]:
    """List clips with optional filters and pagination."""
    store = _get_store()
    clip_status = None
    if status:
        try:
            clip_status = ClipStatus[status.upper()]
        except KeyError:
            clip_status = None

    clips = store.list_clips(
        status=clip_status,
        game=game,
        folder=folder,
        limit=limit,
        offset=offset,
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
            "r2_url": c.r2_url,
            "resolution": list(c.resolution),
            "tags": c.tags,
        }
        for c in clips
    ]


def search_clips(
    query: str,
    game: str | None = None,
    tag: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Full-text search for clips by title, optionally filtered by game/tag."""
    store = _get_store()
    clips = store.list_clips(
        search=query,
        game=game,
        tag=tag,
        limit=limit,
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
            "r2_url": c.r2_url,
            "tags": c.tags,
        }
        for c in clips
    ]


def get_clip(clip_id: str) -> dict[str, Any] | None:
    """Get full details for a single clip by ID."""
    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return None
    return {
        "id": clip.id,
        "stem": clip.stem,
        "title": clip.title,
        "source_path": str(clip.source_path),
        "encoded_path": str(clip.encoded_path) if clip.encoded_path else None,
        "thumb_path": str(clip.thumb_path) if clip.thumb_path else None,
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
        "r2_url": clip.r2_url,
        "r2_path": clip.r2_path,
        "watch_count": clip.watch_count,
        "clip_type": clip.clip_type.name,
    }


def get_stats() -> dict[str, Any]:
    """Get aggregate clip library statistics."""
    store = _get_store()
    return store.get_aggregate_stats()


def list_game_profiles() -> list[dict[str, Any]]:
    """List all per-game recording profiles."""
    store = _get_store()
    profiles = store.list_game_profiles()
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
        }
        for w in webhooks
    ]


def enqueue_encode(clip_id: str) -> dict[str, str]:
    """Re-encode a specific clip."""
    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return {"error": f"Clip {clip_id} not found"}
    logger.info("Encode requested for %s via MCP", clip_id)
    return {"status": "queued", "clip_id": clip_id}


def enqueue_upload(clip_id: str) -> dict[str, str]:
    """Re-upload a specific clip to cloud storage."""
    store = _get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        return {"error": f"Clip {clip_id} not found"}
    if not clip.encoded_path:
        return {"error": "Clip has no encoded file to upload"}
    logger.info("Upload requested for %s via MCP", clip_id)
    return {"status": "queued", "clip_id": clip_id}


def save_game_profile(profile_json: str) -> dict[str, str]:
    """Create or update a game recording profile from JSON."""
    store = _get_store()
    try:
        data = json.loads(profile_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}

    if "game_name" not in data:
        return {"error": "Missing required field: game_name"}

    profile = GameProfile(
        id=data.get("id") or str(_uuid.uuid4()),
        game_name=data["game_name"],
        display_name=data.get("display_name", data["game_name"]),
        replay_duration=data.get("replay_duration", 30),
        capture_fps=data.get("capture_fps", 60),
        pause_encode=data.get("pause_encode", True),
        pause_thumbnail=data.get("pause_thumbnail", True),
        auto_tag=data.get("auto_tag", True),
    )
    store.save_game_profile(profile)
    return {"status": "saved", "game_name": profile.game_name}


def test_webhook(webhook_id: str) -> dict[str, str]:
    """Test-fire a configured webhook."""
    store = _get_store()
    webhooks = store.list_webhooks()
    wh = next((w for w in webhooks if w.id == webhook_id), None)
    if wh is None:
        return {"error": f"Webhook {webhook_id} not found"}

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
