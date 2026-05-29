"""Tests for mcp/tools.py — MCP tool functions with in-memory store."""

from __future__ import annotations

from pathlib import Path

import pytest

from moment.core.models import Clip, ClipStatus, GameProfile, Webhook
from moment.core.store import Store


@pytest.fixture(autouse=True)
def _reset_store_global() -> None:
    """Reset the lazy store singleton between tests."""
    import moment.mcp.tools as mod

    mod._store = None
    yield
    mod._store = None


@pytest.fixture
def mcp_store(store: Store) -> Store:
    """Inject a test store into the module-level singleton."""
    import moment.mcp.tools as mod

    mod._store = store
    return store


class TestListClips:
    def test_empty_store_returns_empty(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_clips

        result = list_clips()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_clip_summaries(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_clips

        clip = Clip(
            id="c1",
            stem="test_clip",
            source_path=Path("/tmp/c1.mkv"),
            duration=30.0,
            file_size=10_000_000,
            title="My Clip",
            game="cs2",
            status=ClipStatus.DONE,
            resolution=(1920, 1080),
            tags=["frag"],
        )
        mcp_store.insert_clip(clip)
        mcp_store.set_tags("c1", ["frag"])

        result = list_clips()
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        assert result[0]["title"] == "My Clip"
        assert result[0]["game"] == "cs2"
        assert result[0]["status"] == "DONE"
        assert result[0]["tags"] == ["frag"]
        assert result[0]["resolution"] == [1920, 1080]

    def test_filter_by_status(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_clips

        mcp_store.insert_clip(Clip(
            id="c1", stem="s1", source_path=Path("/tmp/c1.mkv"),
            status=ClipStatus.DONE,
        ))
        mcp_store.insert_clip(Clip(
            id="c2", stem="s2", source_path=Path("/tmp/c2.mkv"),
            status=ClipStatus.PENDING,
        ))

        result = list_clips(status="DONE")
        assert all(c["status"] == "DONE" for c in result)

    def test_pagination(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_clips

        for i in range(5):
            mcp_store.insert_clip(Clip(
                id=f"c{i}", stem=f"s{i}",
                source_path=Path(f"/tmp/c{i}.mkv"),
            ))

        result = list_clips(limit=3, offset=0)
        assert len(result) == 3


class TestSearchClips:
    def test_search_by_title(self, mcp_store: Store) -> None:
        from moment.mcp.tools import search_clips

        mcp_store.insert_clip(Clip(
            id="c1", stem="ace", source_path=Path("/tmp/c1.mkv"),
            title="Amazing Ace", game="cs2",
        ))
        mcp_store.insert_clip(Clip(
            id="c2", stem="whiff", source_path=Path("/tmp/c2.mkv"),
            title="Terrible Whiff",
        ))

        result = search_clips(query="Ace")
        assert len(result) == 1
        assert result[0]["title"] == "Amazing Ace"

    def test_search_by_game(self, mcp_store: Store) -> None:
        from moment.mcp.tools import search_clips

        mcp_store.insert_clip(Clip(
            id="c1", stem="s1", source_path=Path("/tmp/c1.mkv"),
            title="Clip 1", game="cs2",
        ))
        mcp_store.insert_clip(Clip(
            id="c2", stem="s2", source_path=Path("/tmp/c2.mkv"),
            title="Clip 2", game="valorant",
        ))

        result = search_clips(query="Clip", game="cs2")
        assert len(result) == 1
        assert result[0]["game"] == "cs2"


class TestGetClip:
    def test_get_existing(self, mcp_store: Store) -> None:
        from moment.mcp.tools import get_clip

        mcp_store.insert_clip(Clip(
            id="c1", stem="test", source_path=Path("/tmp/c1.mkv"),
            duration=30.0, file_size=1000, video_codec="h264",
            fps=60.0, resolution=(1920, 1080),
            has_mic_audio=True, has_game_audio=True,
            title="Full Clip", game="cs2",
            status=ClipStatus.UPLOADED,
            r2_url="https://example.com/c1.mp4",
            r2_path="c1.mp4",
        ))
        mcp_store.set_tags("c1", ["ace"])

        result = get_clip("c1")
        assert result is not None
        assert result["id"] == "c1"
        assert result["title"] == "Full Clip"
        assert result["duration"] == 30.0
        assert result["video_codec"] == "h264"
        assert result["fps"] == 60.0
        assert result["resolution"] == [1920, 1080]
        assert result["has_mic_audio"] is True
        assert result["has_game_audio"] is True
        assert result["status"] == "UPLOADED"
        assert result["r2_url"] == "https://example.com/c1.mp4"
        assert result["r2_path"] == "c1.mp4"
        assert result["tags"] == ["ace"]

    def test_get_nonexistent(self, mcp_store: Store) -> None:
        from moment.mcp.tools import get_clip

        result = get_clip("nonexistent")
        assert result is None

    def test_get_clip_with_nulls(self, mcp_store: Store) -> None:
        from moment.mcp.tools import get_clip

        mcp_store.insert_clip(Clip(
            id="min", stem="minimal", source_path=Path("/tmp/min.mkv"),
        ))
        result = get_clip("min")
        assert result is not None
        assert result["encoded_path"] is None
        assert result["thumb_path"] is None
        assert result["uploaded_at"] is None
        assert result["r2_url"] is None


class TestGetStats:
    def test_empty_stats(self, mcp_store: Store) -> None:
        from moment.mcp.tools import get_stats

        stats = get_stats()
        assert stats["total_clips"] == 0
        assert stats["total_storage_bytes"] == 0

    def test_stats_with_clips(self, mcp_store: Store) -> None:
        from datetime import datetime, timezone

        from moment.mcp.tools import get_stats

        now = datetime.now(timezone.utc)
        mcp_store.insert_clip(Clip(
            id="c1", stem="s1", source_path=Path("/tmp/c1.mkv"),
            file_size=5_000_000, game="cs2",
            uploaded_at=now,
        ))
        mcp_store.insert_clip(Clip(
            id="c2", stem="s2", source_path=Path("/tmp/c2.mkv"),
            file_size=3_000_000, game="cs2",
            uploaded_at=now,
        ))

        stats = get_stats()
        assert stats["total_clips"] == 2
        assert stats["total_storage_bytes"] == 8_000_000


class TestListGameProfiles:
    def test_empty(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_game_profiles

        result = list_game_profiles()
        assert result == []

    def test_with_profiles(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_game_profiles

        mcp_store.save_game_profile(GameProfile(
            id="gp1", game_name="cs2", display_name="Counter-Strike 2",
            replay_duration=120, capture_fps=60,
            pause_encode=True, auto_tag=True,
        ))

        result = list_game_profiles()
        assert len(result) == 1
        assert result[0]["game_name"] == "cs2"
        assert result[0]["replay_duration"] == 120
        assert result[0]["capture_fps"] == 60


class TestListWebhooks:
    def test_empty(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_webhooks

        result = list_webhooks()
        assert result == []

    def test_url_is_redacted(self, mcp_store: Store) -> None:
        from moment.mcp.tools import list_webhooks

        mcp_store.save_webhook(Webhook(
            id="wh1", url="https://discord.com/api/webhooks/secret",
            name="Main",
        ))

        result = list_webhooks()
        assert len(result) == 1
        assert result[0]["name"] == "Main"
        assert "url" not in result[0]


# ---------------------------------------------------------------------------
# Mutation tools
# ---------------------------------------------------------------------------


class TestEnqueueEncode:
    def test_enqueue_valid_clip(self, mcp_store: Store) -> None:
        from moment.mcp.tools import enqueue_encode

        mcp_store.insert_clip(Clip(
            id="c1", stem="test", source_path=Path("/tmp/c1.mkv"),
        ))
        result = enqueue_encode("c1")
        assert result["status"] == "queued"
        assert result["clip_id"] == "c1"

    def test_enqueue_missing_clip(self, mcp_store: Store) -> None:
        from moment.mcp.tools import enqueue_encode

        result = enqueue_encode("missing")
        assert "error" in result


class TestEnqueueUpload:
    def test_enqueue_no_encoded_path(self, mcp_store: Store) -> None:
        from moment.mcp.tools import enqueue_upload

        mcp_store.insert_clip(Clip(
            id="c1", stem="test", source_path=Path("/tmp/c1.mkv"),
        ))
        result = enqueue_upload("c1")
        assert "error" in result

    def test_enqueue_with_encoded_path(self, mcp_store: Store) -> None:
        from moment.mcp.tools import enqueue_upload

        mcp_store.insert_clip(Clip(
            id="c1", stem="test", source_path=Path("/tmp/c1.mkv"),
            encoded_path=Path("/tmp/c1_encoded.mp4"),
        ))
        result = enqueue_upload("c1")
        assert result["status"] == "queued"


class TestSaveGameProfile:
    def test_save_valid_profile(self, mcp_store: Store) -> None:
        import json

        from moment.mcp.tools import save_game_profile

        data = {
            "game_name": "minecraft",
            "display_name": "Minecraft",
            "replay_duration": 60,
        }
        result = save_game_profile(json.dumps(data))
        assert result["status"] == "saved"
        assert result["game_name"] == "minecraft"

    def test_missing_game_name(self, mcp_store: Store) -> None:
        import json

        from moment.mcp.tools import save_game_profile

        result = save_game_profile(json.dumps({"display_name": "Test"}))
        assert "error" in result

    def test_invalid_json(self, mcp_store: Store) -> None:
        from moment.mcp.tools import save_game_profile

        result = save_game_profile("not json")
        assert "error" in result


class TestTestWebhook:
    def test_missing_webhook(self, mcp_store: Store) -> None:
        from moment.mcp.tools import test_webhook

        result = test_webhook("missing")
        assert "error" in result
