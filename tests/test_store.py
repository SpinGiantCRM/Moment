"""Tests for core/store.py — full CRUD validation with temp SQLite database."""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from moment.core.models import (
    Bookmark,
    Clip,
    ClipStatus,
    ClipType,
    ClipVisibility,
    EditProfile,
    FilterConfig,
    Folder,
    GameProfile,
    ReviewCardConfig,
    SegmentEdit,
    Tag,
    Task,
    TaskKind,
    TaskStatus,
    Webhook,
    WebhookLogEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clip(store, **overrides) -> Clip:
    clip = Clip(
        id=overrides.pop("id", str(uuid.uuid4())),
        stem=overrides.pop("stem", "2026-05-01_12-00-00"),
        source_path=Path("/tmp/test-clip.mkv"),
        **overrides,
    )
    return store.insert_clip(clip)


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

class TestClipCRUD:
    def test_insert_and_get(self, store) -> None:
        clip = _make_clip(store, title="My Clip")
        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert fetched.title == "My Clip"
        assert fetched.status == ClipStatus.PENDING

    def test_get_nonexistent(self, store) -> None:
        assert store.get_clip("nonexistent") is None

    def test_update(self, store) -> None:
        clip = _make_clip(store, title="Original")
        clip.title = "Updated"
        clip.favorite = True
        store.update_clip(clip)
        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert fetched.title == "Updated"
        assert fetched.favorite is True

    def test_soft_delete(self, store) -> None:
        clip = _make_clip(store)
        store.delete_clip(clip.id, soft=True)
        # Should be excluded from list by default
        clips = store.list_clips()
        assert all(c.id != clip.id for c in clips)

        # Should appear if include_deleted=True
        clips = store.list_clips(include_deleted=True)
        assert any(c.id == clip.id and c.deleted_at is not None for c in clips)

    def test_hard_delete(self, store) -> None:
        clip = _make_clip(store)
        store.delete_clip(clip.id, soft=False)
        assert store.get_clip(clip.id) is None


class TestClipListing:
    def test_list_all(self, store) -> None:
        _make_clip(store)
        _make_clip(store)
        clips = store.list_clips()
        assert len(clips) >= 2

    def test_filter_by_status(self, store) -> None:
        _make_clip(store, status=ClipStatus.UPLOADED)
        _make_clip(store, status=ClipStatus.PENDING)
        uploaded = store.list_clips(status=ClipStatus.UPLOADED)
        assert all(c.status == ClipStatus.UPLOADED for c in uploaded)

    def test_filter_by_game(self, store) -> None:
        _make_clip(store, game="cs2")
        _make_clip(store, game="valorant")
        cs_clips = store.list_clips(game="cs2")
        assert all(c.game == "cs2" for c in cs_clips)

    def test_filter_favorites(self, store) -> None:
        _make_clip(store, favorite=True)
        _make_clip(store, favorite=False)
        favs = store.list_clips(favorite_only=True)
        assert all(c.favorite for c in favs)

    def test_search(self, store) -> None:
        _make_clip(store, title="Awesome CS2 Ace")
        _make_clip(store, title="Random Clip")
        results = store.list_clips(search="Ace")
        assert len(results) == 1
        assert results[0].title == "Awesome CS2 Ace"

    def test_pagination(self, store) -> None:
        for i in range(10):
            _make_clip(store, title=f"Clip {i}")
        page = store.list_clips(limit=3, offset=0)
        assert len(page) == 3
        page2 = store.list_clips(limit=3, offset=3)
        assert len(page2) == 3
        assert page[0].id != page2[0].id


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    def test_set_and_sync_tags(self, store) -> None:
        clip = _make_clip(store)
        store.set_tags(clip.id, ["frag", "ace"])
        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert set(fetched.tags) == {"frag", "ace"}

    def test_list_tags(self, store) -> None:
        clip = _make_clip(store)
        store.set_tags(clip.id, ["frag", "ace", "clutch"])
        tags = store.list_tags()
        tag_names = {t.name for t in tags}
        assert tag_names >= {"frag", "ace", "clutch"}

    def test_delete_tag(self, store) -> None:
        clip = _make_clip(store)
        store.set_tags(clip.id, ["temp"])
        tags = store.list_tags()
        tag_id = next(t.id for t in tags if t.name == "temp")
        store.delete_tag(tag_id)
        tags = store.list_tags()
        assert not any(t.name == "temp" for t in tags)

    def test_set_tags_overwrite(self, store) -> None:
        clip = _make_clip(store)
        store.set_tags(clip.id, ["old"])
        store.set_tags(clip.id, ["new"])
        fetched = store.get_clip(clip.id)
        assert fetched is not None
        assert fetched.tags == ["new"]


# ---------------------------------------------------------------------------
# EditProfile
# ---------------------------------------------------------------------------

class TestEditProfile:
    def test_get_nonexistent(self, store) -> None:
        assert store.get_edit_profile("nonexistent") is None

    def test_save_and_get(self, store) -> None:
        _make_clip(store, id="test-clip")
        ep = EditProfile(clip_id="test-clip", trim_start=2.0, trim_end=28.0)
        store.save_edit_profile(ep)
        fetched = store.get_edit_profile("test-clip")
        assert fetched is not None
        assert fetched.trim_start == 2.0
        assert fetched.trim_end == 28.0

    def test_persists_segments(self, store) -> None:
        _make_clip(store, id="test-clip-2")
        ep = EditProfile(
            clip_id="test-clip-2",
            segments=[SegmentEdit(start=5.0, end=10.0, speed=2.0)],
            game_audio_volume=0.8,
        )
        store.save_edit_profile(ep)
        fetched = store.get_edit_profile("test-clip-2")
        assert fetched is not None
        assert len(fetched.segments) == 1
        assert fetched.segments[0].speed == 2.0
        assert fetched.game_audio_volume == 0.8

    def test_persists_filters(self, store) -> None:
        _make_clip(store, id="test-clip-3")
        ep = EditProfile(
            clip_id="test-clip-3",
            filters=[FilterConfig(filter_name="brightness", params={"value": 1.2})],
        )
        store.save_edit_profile(ep)
        fetched = store.get_edit_profile("test-clip-3")
        assert fetched is not None
        assert len(fetched.filters) == 1
        assert fetched.filters[0].filter_name == "brightness"


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

class TestBookmarks:
    def test_insert_and_query(self, store) -> None:
        bm = Bookmark(id="bm1", session_stem="session1", offset_seconds=10.0, label="nice shot")
        store.insert_bookmark(bm)
        results = store.get_bookmarks_for_session("session1")
        assert len(results) == 1
        assert results[0].label == "nice shot"

    def test_delete(self, store) -> None:
        bm = Bookmark(id="bm2", session_stem="session2", offset_seconds=5.0)
        store.insert_bookmark(bm)
        store.delete_bookmark("bm2")
        assert len(store.get_bookmarks_for_session("session2")) == 0


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class TestWebhooks:
    def test_save_and_list(self, store) -> None:
        wh = Webhook(id="wh1", url="https://discord.com/api/webhooks/1", name="Main")
        store.save_webhook(wh)
        hooks = store.list_webhooks()
        assert len(hooks) >= 1
        assert hooks[0].name == "Main"

    def test_delete(self, store) -> None:
        wh = Webhook(id="wh-del", url="https://discord.com/api/webhooks/2")
        store.save_webhook(wh)
        store.delete_webhook("wh-del")
        assert not any(w.id == "wh-del" for w in store.list_webhooks())

    def test_log_entry(self, store) -> None:
        wh = Webhook(id="wh1", url="https://discord.com/api/webhooks/1")
        store.save_webhook(wh)
        _make_clip(store, id="c1")
        entry = WebhookLogEntry(
            id="wl1", webhook_id="wh1", clip_id="c1",
            success=False, status_code=404, error_message="Not found",
        )
        store.insert_webhook_log(entry)
        # Log is stored but not queried via public API yet


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

class TestFolders:
    def test_save_and_list(self, store) -> None:
        f = Folder(id="f1", name="Highlights")
        store.save_folder(f)
        folders = store.list_folders()
        assert any(fld.name == "Highlights" for fld in folders)

    def test_delete(self, store) -> None:
        f = Folder(id="f-del", name="Temp")
        store.save_folder(f)
        store.delete_folder("f-del")
        assert not any(fld.name == "Temp" for fld in store.list_folders())


# ---------------------------------------------------------------------------
# Game profiles
# ---------------------------------------------------------------------------

class TestGameProfiles:
    def test_save_and_get(self, store) -> None:
        gp = GameProfile(id="gp1", game_name="cs2", display_name="Counter-Strike 2")
        store.save_game_profile(gp)
        fetched = store.get_game_profile("cs2")
        assert fetched is not None
        assert fetched.display_name == "Counter-Strike 2"

    def test_with_review_card(self, store) -> None:
        rc = ReviewCardConfig(size="small", preview_duration=10.0)
        gp = GameProfile(id="gp2", game_name="valorant", display_name="Valorant", review_card=rc)
        store.save_game_profile(gp)
        fetched = store.get_game_profile("valorant")
        assert fetched is not None
        assert fetched.review_card is not None
        assert fetched.review_card.size == "small"

    def test_list(self, store) -> None:
        store.save_game_profile(GameProfile(id="gp-a", game_name="a", display_name="A"))
        store.save_game_profile(GameProfile(id="gp-b", game_name="b", display_name="B"))
        assert len(store.list_game_profiles()) >= 2

    def test_delete(self, store) -> None:
        store.save_game_profile(GameProfile(id="gp-del", game_name="del", display_name="D"))
        store.delete_game_profile("del")
        assert store.get_game_profile("del") is None

    def test_get_nonexistent(self, store) -> None:
        assert store.get_game_profile("nonexistent") is None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TestTasks:
    def test_insert_and_query_pending(self, store) -> None:
        task = Task(id="t1", type=TaskKind.ENCODE, priority=5, payload={"clip_id": "c1"})
        store.insert_task(task)
        pending = store.get_pending_tasks()
        assert any(t.id == "t1" for t in pending)

    def test_update_status(self, store) -> None:
        task = Task(id="t2", type=TaskKind.THUMBNAIL)
        store.insert_task(task)
        store.update_task_status("t2", TaskStatus.COMPLETED)
        pending = store.get_pending_tasks()
        assert not any(t.id == "t2" for t in pending)

    def test_update_with_error(self, store) -> None:
        task = Task(id="t3", type=TaskKind.UPLOAD)
        store.insert_task(task)
        store.update_task_status("t3", TaskStatus.FAILED, error_message="Upload timeout")
        pending = store.get_pending_tasks()
        assert not any(t.id == "t3" for t in pending)

# ---------------------------------------------------------------------------
# URL History
# ---------------------------------------------------------------------------

class TestURLHistory:
    def test_insert_and_get(self, store) -> None:
        _make_clip(store, id="url-test-clip")
        store.insert_url_history("url-test-clip", "https://r2.example.com/clip1.mp4")
        store.insert_url_history("url-test-clip", "https://r2.example.com/clip1-v2.mp4")
        history = store.get_url_history("url-test-clip")
        assert len(history) == 2
        urls = {h["url"] for h in history}
        assert "https://r2.example.com/clip1.mp4" in urls
        assert "https://r2.example.com/clip1-v2.mp4" in urls


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class TestMigration:
    def test_migrate_nonexistent_file(self, store) -> None:
        count = store.migrate_from_json(Path("/tmp/nonexistent_clips.json"))
        assert count == 0

    def test_migrate_valid_json(self, store) -> None:
        import os
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="clip_migration_test_")
        os.close(fd)
        data = [
            {
                "id": "old-clip-1",
                "stem": "2025-01-01_10-00-00",
                "source_path": "/tmp/old1.mkv",
                "duration": 30,
                "file_size": 10_000,
                "title": "Old Clip",
                "game": "csgo",
            },
        ]
        with open(tmp_path, "w") as f:
            json.dump(data, f)

        try:
            count = store.migrate_from_json(Path(tmp_path))
            assert count == 1
            clip = store.get_clip("old-clip-1")
            assert clip is not None
            assert clip.title == "Old Clip"
            assert clip.game == "csgo"
            # File should have been renamed to .bak
            assert not os.path.exists(tmp_path)
            assert os.path.exists(tmp_path + ".bak")
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            try:
                os.unlink(tmp_path + ".bak")
            except FileNotFoundError:
                pass

    def test_migrate_already_populated(self, store) -> None:
        """If DB already has clips, JSON is renamed without importing."""
        _make_clip(store, id="existing")
        import os
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="clip_migration_test_")
        os.close(fd)
        with open(tmp_path, "w") as f:
            json.dump([{"id": "dup", "stem": "test", "source_path": "/tmp/dup.mkv", "title": "Duplicate"}], f)
        try:
            count = store.migrate_from_json(Path(tmp_path))
            assert count == 0  # No new clips imported
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            try:
                os.unlink(tmp_path + ".bak")
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# Thread Safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_lock_exists(self, store) -> None:
        """Store should have a threading lock for write operations."""
        import threading
        assert hasattr(store, "_lock")
        assert isinstance(store._lock, type(threading.Lock()))

    def test_concurrent_inserts(self, store) -> None:
        """Multiple threads should be able to insert clips without corruption."""
        import threading
        errors = []

        def insert_clip(i: int) -> None:
            try:
                clip = Clip(
                    id=f"thread-clip-{i}",
                    stem=f"thread-{i}",
                    source_path=Path(f"/tmp/thread-{i}.mkv"),
                )
                store.insert_clip(clip)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=insert_clip, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All clips should be there
        for i in range(20):
            c = store.get_clip(f"thread-clip-{i}")
            assert c is not None, f"Clip thread-clip-{i} was not found"
