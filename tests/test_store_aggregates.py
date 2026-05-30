"""Tests for aggregate store methods added in Batch 2 (spec-eight).

Covers: get_aggregate_stats, list_webhook_logs, clear_webhook_logs,
restore_clip, empty_trash.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from moment.core.models import (
    Clip,
    Webhook,
    WebhookLogEntry,
)


def _make_clip(store, **overrides) -> Clip:
    clip = Clip(
        id=overrides.pop("id", str(uuid.uuid4())),
        stem=overrides.pop("stem", "2026-05-01_12-00-00"),
        source_path=Path("/tmp/test-clip.mkv"),
        **overrides,
    )
    return store.insert_clip(clip)


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


class TestAggregateStats:
    def test_empty_db(self, store) -> None:
        stats = store.get_aggregate_stats()
        assert stats["total_clips"] == 0
        assert stats["total_storage_bytes"] == 0
        assert stats["uploads_today"] == 0
        assert stats["uploads_this_week"] == 0
        assert stats["clips_per_game"] == []
        assert stats["uploads_per_day"] == []
        assert stats["recent_uploads"] == []

    def test_total_clips(self, store) -> None:
        _make_clip(store)
        _make_clip(store)
        _make_clip(store)
        stats = store.get_aggregate_stats()
        assert stats["total_clips"] == 3

    def test_soft_deleted_excluded(self, store) -> None:
        _make_clip(store)
        c = _make_clip(store)
        store.delete_clip(c.id, soft=True)
        stats = store.get_aggregate_stats()
        assert stats["total_clips"] == 1

    def test_total_storage(self, store) -> None:
        _make_clip(store, file_size=1_000_000)
        _make_clip(store, file_size=2_500_000)
        stats = store.get_aggregate_stats()
        assert stats["total_storage_bytes"] == 3_500_000

    def test_uploads_today(self, store) -> None:
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _make_clip(store, uploaded_at=datetime.now(timezone.utc))
        stats = store.get_aggregate_stats()
        assert stats["uploads_today"] >= 1

    def test_uploads_per_day(self, store) -> None:
        """Uploads per day should return at least today's entry."""
        _make_clip(store)
        stats = store.get_aggregate_stats()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert any(d["date"] == today for d in stats["uploads_per_day"])

    def test_clips_per_game(self, store) -> None:
        _make_clip(store, game="cs2", file_size=1000)
        _make_clip(store, game="cs2", file_size=2000)
        _make_clip(store, game="valorant", file_size=3000)
        stats = store.get_aggregate_stats()
        game_data = {d["game"]: d for d in stats["clips_per_game"]}
        assert game_data["cs2"]["count"] == 2
        assert game_data["cs2"]["storage"] == 3000
        assert game_data["valorant"]["count"] == 1
        assert game_data["valorant"]["storage"] == 3000

    def test_none_game_becomes_unknown(self, store) -> None:
        _make_clip(store, game=None)
        stats = store.get_aggregate_stats()
        assert stats["clips_per_game"][0]["game"] == "Unknown"

    def test_recent_uploads(self, store) -> None:
        for i in range(12):
            _make_clip(
                store,
                title=f"Clip {i}",
                uploaded_at=datetime.now(timezone.utc),
                file_size=1000 * i,
            )
        stats = store.get_aggregate_stats()
        assert len(stats["recent_uploads"]) == 10  # LIMIT 10

    def test_recent_uploads_only_uploaded(self, store) -> None:
        """Non-uploaded clips should not appear in recent_uploads."""
        _make_clip(store, title="Not uploaded", uploaded_at=None)
        stats = store.get_aggregate_stats()
        assert not any(u["title"] == "Not uploaded" for u in stats["recent_uploads"])


# ---------------------------------------------------------------------------
# Webhook logs
# ---------------------------------------------------------------------------


class TestWebhookLogs:
    def _setup_webhooks(self, store) -> tuple[str, str]:
        wh1 = Webhook(id="wh-a", url="https://discord.com/api/webhooks/a", name="A")
        wh2 = Webhook(id="wh-b", url="https://discord.com/api/webhooks/b", name="B")
        store.save_webhook(wh1)
        store.save_webhook(wh2)
        _make_clip(store, id="c1")
        _make_clip(store, id="c2")
        return "wh-a", "wh-b"

    def test_list_all(self, store) -> None:
        self._setup_webhooks(store)
        e1 = WebhookLogEntry(
            id="wl1", webhook_id="wh-a", clip_id="c1", success=True, status_code=200
        )
        e2 = WebhookLogEntry(
            id="wl2", webhook_id="wh-b", clip_id="c2",
            success=False, status_code=404, error_message="Not found",
        )
        store.insert_webhook_log(e1)
        store.insert_webhook_log(e2)

        entries = store.list_webhook_logs()
        assert len(entries) == 2

    def test_filter_by_webhook(self, store) -> None:
        self._setup_webhooks(store)
        store.insert_webhook_log(WebhookLogEntry(
            id="wl1", webhook_id="wh-a", clip_id="c1", success=True, status_code=200
        ))
        store.insert_webhook_log(WebhookLogEntry(
            id="wl2", webhook_id="wh-b", clip_id="c2",
            success=False, status_code=404,
        ))

        entries = store.list_webhook_logs(webhook_id="wh-a")
        assert len(entries) == 1
        assert entries[0].webhook_id == "wh-a"

    def test_filter_by_success(self, store) -> None:
        self._setup_webhooks(store)
        _insert_log = store.insert_webhook_log
        _insert_log(WebhookLogEntry(
            id="wl1", webhook_id="wh-a", clip_id="c1", success=True, status_code=200
        ))
        _insert_log(WebhookLogEntry(
            id="wl2", webhook_id="wh-a", clip_id="c2",
            success=False, status_code=500,
        ))

        success_entries = store.list_webhook_logs(success=True)
        assert len(success_entries) == 1
        assert success_entries[0].success is True

        fail_entries = store.list_webhook_logs(success=False)
        assert len(fail_entries) == 1
        assert fail_entries[0].success is False

    def test_combined_filters(self, store) -> None:
        self._setup_webhooks(store)
        _insert_log = store.insert_webhook_log
        _insert_log(WebhookLogEntry(
            id="wl1", webhook_id="wh-a", clip_id="c1", success=True, status_code=200
        ))
        _insert_log(WebhookLogEntry(
            id="wl2", webhook_id="wh-a", clip_id="c2",
            success=False, status_code=500,
        ))
        _insert_log(WebhookLogEntry(
            id="wl3", webhook_id="wh-b", clip_id="c1", success=True, status_code=200
        ))

        entries = store.list_webhook_logs(webhook_id="wh-a", success=False)
        assert len(entries) == 1
        assert entries[0].webhook_id == "wh-a"
        assert entries[0].success is False

    def test_pagination(self, store) -> None:
        self._setup_webhooks(store)
        for i in range(5):
            store.insert_webhook_log(
                WebhookLogEntry(
                    id=f"wl-p{i}", webhook_id="wh-a",
                    clip_id="c1", success=True, status_code=200,
                )
            )

        page1 = store.list_webhook_logs(limit=3, offset=0)
        assert len(page1) == 3

        page2 = store.list_webhook_logs(limit=3, offset=3)
        assert len(page2) == 2

    def test_clear_logs(self, store) -> None:
        self._setup_webhooks(store)
        store.insert_webhook_log(WebhookLogEntry(
            id="wl1", webhook_id="wh-a", clip_id="c1", success=True, status_code=200
        ))
        store.insert_webhook_log(WebhookLogEntry(
            id="wl2", webhook_id="wh-a", clip_id="c2",
            success=False, status_code=404,
        ))

        store.clear_webhook_logs()
        assert len(store.list_webhook_logs()) == 0

    def test_empty_log(self, store) -> None:
        """Listing logs on a fresh DB should return empty list."""
        entries = store.list_webhook_logs()
        assert entries == []


# ---------------------------------------------------------------------------
# Trash operations
# ---------------------------------------------------------------------------


class TestTrashOperations:
    def test_restore_clip(self, store) -> None:
        clip = _make_clip(store)
        store.delete_clip(clip.id, soft=True)

        # Verify it's deleted
        assert store.get_clip(clip.id) is not None  # Soft-deleted still retrievable
        clips = store.list_clips()
        assert not any(c.id == clip.id for c in clips)  # Excluded from normal listing

        # Restore
        result = store.restore_clip(clip.id)
        assert result is True

        # Verify restored
        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert fetched.deleted_at is None

        # Should appear in normal listing now
        clips = store.list_clips()
        assert any(c.id == clip.id for c in clips)

    def test_restore_nonexistent(self, store) -> None:
        result = store.restore_clip("nonexistent")
        assert result is False

    def test_restore_not_deleted(self, store) -> None:
        """Restoring a non-deleted clip should return False (no row modified)."""
        clip = _make_clip(store)
        result = store.restore_clip(clip.id)
        # Clip is not deleted, so no row matches the UPDATE
        assert result is False

    def test_empty_trash(self, store) -> None:
        c1 = _make_clip(store)
        c2 = _make_clip(store)
        _make_clip(store)  # active clip stays
        store.delete_clip(c1.id, soft=True)
        store.delete_clip(c2.id, soft=True)

        count = store.empty_trash()
        assert count == 2

        # Deleted clips are gone (hard-deleted)
        assert store.get_clip(c1.id) is None
        assert store.get_clip(c2.id) is None

    def test_empty_trash_nothing(self, store) -> None:
        """Emptying trash with no soft-deleted clips should return 0."""
        _make_clip(store)
        count = store.empty_trash()
        assert count == 0

    def test_restored_clip_preserves_data(self, store) -> None:
        clip = _make_clip(store, title="My Precious", game="cs2", file_size=9999, favorite=True)
        store.delete_clip(clip.id, soft=True)
        store.restore_clip(clip.id)

        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert fetched.title == "My Precious"
        assert fetched.game == "cs2"
        assert fetched.file_size == 9999
        assert fetched.favorite is True
        assert fetched.deleted_at is None

    def test_empty_trash_clears_count_before_delete(self, store) -> None:
        """Empty trash returns the count of clips that were removed."""
        for i in range(5):
            c = _make_clip(store)
            if i < 3:
                store.delete_clip(c.id, soft=True)

        count = store.empty_trash()
        assert count == 3

        # Active clips remain
        stats = store.get_aggregate_stats()
        assert stats["total_clips"] == 2
