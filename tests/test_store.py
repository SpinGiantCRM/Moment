"""Tests for core/store.py — full CRUD validation with temp SQLite database."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.models import (
    Bookmark,
    Clip,
    ClipStatus,
    ClipVisibility,
    EditProfile,
    FilterConfig,
    Folder,
    GameProfile,
    ReviewCardConfig,
    SegmentEdit,
    Task,
    TaskKind,
    TaskStatus,
    Webhook,
    WebhookLogEntry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.integration]


def _make_clip(store, **overrides) -> Clip:
    source_path = overrides.pop("source_path", Path("/tmp/test-clip.mkv"))
    if isinstance(source_path, str):
        source_path = Path(source_path)
    clip = Clip(
        id=overrides.pop("id", str(uuid.uuid4())),
        stem=overrides.pop("stem", "2026-05-01_12-00-00"),
        source_path=source_path,
        visibility=overrides.pop("visibility", ClipVisibility.PUBLIC),
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
        wh = Webhook(id="wh1", url="https://discord.com/api/webhooks/1/token123", name="Main")
        store.save_webhook(wh)
        hooks = store.list_webhooks()
        assert len(hooks) >= 1
        assert hooks[0].name == "Main"
        # URL should be redacted
        assert "[REDACTED]" in hooks[0].url
        assert "token123" not in hooks[0].url

    def test_list_webhooks_redacted(self, store) -> None:
        """Spec 16: list_webhooks() returns redacted URLs."""

        wh = Webhook(
            id="wh-redact",
            url="https://discord.com/api/webhooks/123456/secret_token_abc",
            name="Test",
        )
        store.save_webhook(wh)
        hooks = store.list_webhooks()
        wh_out = next(w for w in hooks if w.id == "wh-redact")
        assert "secret_token_abc" not in wh_out.url
        assert "[REDACTED]" in wh_out.url

    def test_get_webhook_url_returns_real_url(self, store) -> None:
        """Spec 16: get_webhook_url() decrypts and returns the real URL for dispatch."""
        wh = Webhook(
            id="wh-decrypt",
            url="https://discord.com/api/webhooks/123456/real_token",
            name="Dispatch",
        )
        store.save_webhook(wh)
        real = store.get_webhook_url("wh-decrypt")
        assert real == "https://discord.com/api/webhooks/123456/real_token"

    def test_get_webhook_url_nonexistent(self, store) -> None:
        """Spec 16: get_webhook_url() returns None for missing webhooks."""
        assert store.get_webhook_url("nonexistent") is None

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
# Webhook Security — HTTPS enforcement and encryption
# ---------------------------------------------------------------------------

class TestWebhookSecurity:
    def test_rejects_non_https_url(self, store) -> None:
        """Webhook URLs must be HTTPS."""
        wh = Webhook(id="wh-http", url="http://discord.com/api/webhooks/1/token")
        with pytest.raises(ValueError, match="must be HTTPS"):
            store.save_webhook(wh)

    def test_rejects_ftp_url(self, store) -> None:
        """FTP webhook URLs should be rejected."""
        wh = Webhook(id="wh-ftp", url="ftp://discord.com/api/webhooks/1/token")
        with pytest.raises(ValueError, match="must be HTTPS"):
            store.save_webhook(wh)

    def test_rejects_plain_text_url(self, store) -> None:
        """Plain non-protocol URLs should be rejected."""
        wh = Webhook(id="wh-plain", url="discord.com/api/webhooks/1/token")
        with pytest.raises(ValueError, match="must be HTTPS"):
            store.save_webhook(wh)

    def test_rejects_empty_url(self, store) -> None:
        """Empty webhook URLs should be rejected."""
        wh = Webhook(id="wh-empty", url="")
        with pytest.raises(ValueError, match="must be HTTPS"):
            store.save_webhook(wh)

    def test_encrypted_url_stored_different_from_original(self, store) -> None:
        """The stored URL must be encrypted (not the same as the original)."""
        original_url = "https://discord.com/api/webhooks/123456/secret_token"
        wh = Webhook(id="wh-encrypt-check", url=original_url, name="EncryptCheck")
        store.save_webhook(wh)

        # Read the raw URL from the database (should be encrypted)
        row = store._read_conn.execute(
            "SELECT url FROM webhooks WHERE id = ?", ("wh-encrypt-check",)
        ).fetchone()
        assert row is not None
        stored_url = row["url"]
        # Stored URL should NOT be the original plaintext
        assert stored_url != original_url
        # Original token should not appear in the stored value
        assert "secret_token" not in stored_url

    def test_decrypted_url_matches_original(self, store) -> None:
        """get_webhook_url() should decrypt the stored URL back to the original."""
        original_url = "https://discord.com/api/webhooks/123456/real_token"
        wh = Webhook(id="wh-decrypt-check", url=original_url, name="DecryptCheck")
        store.save_webhook(wh)

        decrypted = store.get_webhook_url("wh-decrypt-check")
        assert decrypted == original_url

    def test_list_webhooks_does_not_leak_token(self, store) -> None:
        """list_webhooks() must redact the token portion of the URL."""
        wh = Webhook(
            id="wh-leak",
            url="https://discord.com/api/webhooks/98765/super_secret_token_xyz",
            name="LeakTest",
        )
        store.save_webhook(wh)

        hooks = store.list_webhooks()
        wh_out = next(w for w in hooks if w.id == "wh-leak")
        assert "super_secret_token_xyz" not in wh_out.url
        assert "[REDACTED]" in wh_out.url

    def test_short_non_discord_url_truncated(self, store) -> None:
        """Non-Discord webhook URLs under 60 chars are returned as-is."""
        short_url = "https://hooks.example.com/webhook/abc"
        wh = Webhook(id="wh-short", url=short_url, name="Short")
        store.save_webhook(wh)

        hooks = store.list_webhooks()
        wh_out = next(w for w in hooks if w.id == "wh-short")
        assert wh_out.url == short_url
        # No redaction needed for non-Discord short URLs
        assert "[REDACTED]" not in wh_out.url

    def test_long_non_discord_url_truncated(self, store) -> None:
        """Non-Discord webhook URLs over 60 chars are truncated."""
        long_url = "https://hooks.example.com/webhook/abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
        assert len(long_url) > 60
        wh = Webhook(id="wh-long", url=long_url, name="Long")
        store.save_webhook(wh)

        hooks = store.list_webhooks()
        wh_out = next(w for w in hooks if w.id == "wh-long")
        assert "..." in wh_out.url
        assert len(wh_out.url) <= 60

    def test_encryption_failure_raises_runtime_error(self, store) -> None:
        """If Fernet encryption fails, save_webhook should raise RuntimeError."""
        wh = Webhook(id="wh-enc-fail", url="https://discord.com/api/webhooks/1/token")
        with (
            patch.object(store, "_get_or_create_fernet", side_effect=Exception("crypto error")),
            pytest.raises(RuntimeError, match="Failed to encrypt"),
        ):
            store.save_webhook(wh)

    def test_decryption_failure_raises_runtime_error(self, store) -> None:
        """If Fernet decryption fails, get_webhook_url should raise RuntimeError."""
        # Insert an encrypted webhook
        wh = Webhook(id="wh-dec-fail", url="https://discord.com/api/webhooks/1/token", name="DecFail")
        store.save_webhook(wh)

        # Corrupt the encrypted value in the database
        store._conn.execute(
            "UPDATE webhooks SET url = ? WHERE id = ?",
            ("garbage-not-valid-fernet-token", "wh-dec-fail"),
        )
        store._conn.commit()

        with pytest.raises(RuntimeError, match="Failed to decrypt"):
            store.get_webhook_url("wh-dec-fail")

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
            for suffix in ("", ".bak"):
                try:
                    os.unlink(tmp_path + suffix)
                except FileNotFoundError:
                    pass

    def test_migrate_already_populated(self, store) -> None:
        """If DB already has clips, JSON is renamed without importing."""
        _make_clip(store, id="existing")
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="clip_migration_test_")
        os.close(fd)
        with open(tmp_path, "w") as f:
            json.dump(
                [{
                    "id": "dup",
                    "stem": "test",
                    "source_path": "/tmp/dup.mkv",
                    "title": "Duplicate",
                }],
                f,
            )
        try:
            count = store.migrate_from_json(Path(tmp_path))
            assert count == 0  # No new clips imported
        finally:
            for suffix in ("", ".bak"):
                try:
                    os.unlink(tmp_path + suffix)
                except FileNotFoundError:
                    pass

    def test_migrate_old_dirs_renames(self, store) -> None:
        """_migrate_old_dirs renames clip-tray dirs to moment dirs."""
        import shutil as _shutil

        old_dir = Path(tempfile.mkdtemp(prefix="clip_tray_", suffix="_data"))
        new_dir = old_dir.parent / f"moment_data_{uuid.uuid4().hex[:8]}"

        try:
            with (
                patch("moment.core.store._OLD_DATA_DIR", str(old_dir)),
                patch("moment.core.store._DEFAULT_DATA_DIR", str(new_dir)),
            ):
                from moment.core.store import Store as _Store

                fd, dbp = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                try:
                    s = _Store(db_path=dbp)
                    # _migrate_old_dirs should rename old_dir to new_dir
                    assert new_dir.exists()
                    s.close()
                finally:
                    for sfx in ("", "-wal", "-shm"):
                        try:
                            os.unlink(dbp + sfx)
                        except FileNotFoundError:
                            pass
        finally:
            for d in (old_dir, new_dir):
                if d.exists():
                    _shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------------------
# Edge cases — empty DB
# ---------------------------------------------------------------------------

class TestEmptyDB:
    def test_list_clips_empty(self, store) -> None:
        assert store.list_clips() == []

    def test_list_clips_with_status_empty(self, store) -> None:
        assert store.list_clips(status=ClipStatus.DONE) == []

    def test_list_tags_empty(self, store) -> None:
        assert store.list_tags() == []

    def test_list_folders_empty(self, store) -> None:
        assert store.list_folders() == []

    def test_list_webhooks_empty(self, store) -> None:
        assert store.list_webhooks() == []

    def test_list_game_profiles_empty(self, store) -> None:
        assert store.list_game_profiles() == []

    def test_get_pending_tasks_empty(self, store) -> None:
        assert store.get_pending_tasks() == []

    def test_get_aggregate_stats_empty(self, store) -> None:
        stats = store.get_aggregate_stats()
        assert stats["total_clips"] == 0
        assert stats["total_storage_bytes"] == 0

    def test_get_clip_none_empty_db(self, store) -> None:
        assert store.get_clip("anything") is None

    def test_get_edit_profile_none_empty_db(self, store) -> None:
        assert store.get_edit_profile("anything") is None

    def test_get_game_profile_none_empty_db(self, store) -> None:
        assert store.get_game_profile("anything") is None

# ---------------------------------------------------------------------------
# Edge cases — malformed data
# ---------------------------------------------------------------------------

class TestMalformedData:
    def test_insert_clip_no_explode(self, store) -> None:
        """Minimal insert with only required fields."""
        clip = Clip(
            id="min",
            stem="min",
            source_path=Path("/tmp/min.mkv"),
        )
        store.insert_clip(clip)
        fetched = store.get_clip("min")
        assert fetched is not None
        assert fetched.duration == 0.0
        assert fetched.file_size == 0

    def test_insert_clip_very_long_title(self, store) -> None:
        """Very long titles should not break the DB."""
        clip = Clip(
            id="long",
            stem="long_title",
            source_path=Path("/tmp/long.mkv"),
            title="A" * 2000,
        )
        store.insert_clip(clip)
        fetched = store.get_clip("long")
        assert fetched is not None
        assert len(fetched.title) == 2000

    def test_insert_clip_unicode(self, store) -> None:
        """Unicode in title, game, and tags should survive round-trip."""
        clip = Clip(
            id="uni",
            stem="unicode",
            source_path=Path("/tmp/uni.mkv"),
            title="🔥 精彩片段",
            game="反恐精英",
        )
        store.insert_clip(clip)
        store.set_tags("uni", ["冠军", "✨"])
        fetched = store.get_clip("uni")
        assert fetched is not None
        assert fetched.title == "🔥 精彩片段"
        assert fetched.game == "反恐精英"
        assert set(fetched.tags) == {"冠军", "✨"}

    def test_insert_clip_null_strings(self, store) -> None:
        """Null/None fields should be handled."""
        clip = Clip(
            id="nulls",
            stem="nulls",
            source_path=Path("/tmp/nulls.mkv"),
            title=None,
            game=None,
            r2_url=None,
            r2_path=None,
        )
        store.insert_clip(clip)
        fetched = store.get_clip("nulls")
        assert fetched is not None
        assert fetched.title == ""
        assert fetched.game is None

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

# ---------------------------------------------------------------------------
# Visibility enforcement (Spec 24)
# ---------------------------------------------------------------------------

class TestVisibilityFiltering:
    def test_guest_excludes_private(self, store) -> None:
        """Guest (no owner_id) should exclude PRIVATE clips."""
        from moment.core.models import ClipVisibility
        _make_clip(store, id="pub-clip", visibility=ClipVisibility.PUBLIC, title="Public")
        _make_clip(store, id="priv-clip", visibility=ClipVisibility.PRIVATE, title="Private")
        _make_clip(store, id="unl-clip", visibility=ClipVisibility.UNLISTED, title="Unlisted")

        clips = store.list_clips()  # default: no owner_id → exclude PRIVATE
        ids = {c.id for c in clips}
        assert "pub-clip" in ids
        assert "unl-clip" in ids
        assert "priv-clip" not in ids

    def test_owner_sees_own_private(self, store) -> None:
        """Owner sees PUBLIC + UNLISTED + their own PRIVATE clips."""
        from moment.core.models import ClipVisibility
        _make_clip(store, id="pub2", visibility=ClipVisibility.PUBLIC, title="Pub")
        _make_clip(store, id="priv-mine", visibility=ClipVisibility.PRIVATE,
                    discord_user_id="user123", title="Mine")
        _make_clip(store, id="priv-other", visibility=ClipVisibility.PRIVATE,
                    discord_user_id="other_user", title="Other")

        clips = store.list_clips(owner_id="user123")
        ids = {c.id for c in clips}
        assert "pub2" in ids
        assert "priv-mine" in ids
        assert "priv-other" not in ids

    def test_explicit_visibility_filter(self, store) -> None:
        """Explicit visibility=X returns only that visibility."""
        from moment.core.models import ClipVisibility
        _make_clip(store, id="pub-only", visibility=ClipVisibility.PUBLIC, title="P")
        _make_clip(store, id="priv-only", visibility=ClipVisibility.PRIVATE, title="X")

        clips = store.list_clips(visibility=ClipVisibility.PUBLIC)
        assert all(c.visibility == ClipVisibility.PUBLIC for c in clips)
        assert any(c.id == "pub-only" for c in clips)
        assert not any(c.id == "priv-only" for c in clips)

    def test_discord_user_id_persists(self, store) -> None:
        """discord_user_id is stored and retrieved."""
        _make_clip(store, id="owner-clip", discord_user_id="user456")
        clip = store.get_clip("owner-clip")
        assert clip is not None
        assert clip.discord_user_id == "user456"

    def test_count_clips_respects_visibility(self, store) -> None:
        """count_clips with no owner excludes PRIVATE."""
        from moment.core.models import ClipVisibility
        _make_clip(store, id="cnt-pub", visibility=ClipVisibility.PUBLIC)
        _make_clip(store, id="cnt-priv", visibility=ClipVisibility.PRIVATE)

        total = store.count_clips()
        assert total == 1  # only public

    def test_migration_adds_discord_user_id_column(self, store) -> None:
        """_migrate_discord_user_id is idempotent and adds column if missing."""
        # Running again should not crash
        store._migrate_discord_user_id()
        # Should be able to insert a clip with the field
        _make_clip(store, id="post-mig", discord_user_id="u1")
        assert store.get_clip("post-mig").discord_user_id == "u1"

# ---------------------------------------------------------------------------
# Spec 6 — Content-aware updated_at
# ---------------------------------------------------------------------------

class TestContentAwareUpdatedAt:
    def test_content_field_change_bumps_updated_at(self, store) -> None:
        clip = _make_clip(store, id="content-at", title="Original")
        old_updated = clip.updated_at

        # Change a content field (file_size)
        clip.file_size = 999_999
        store.update_clip(clip)

        fetched = store.get_clip("content-at")
        assert fetched is not None
        assert fetched.updated_at > old_updated

    def test_metadata_change_leaves_updated_at(self, store) -> None:
        clip = _make_clip(store, id="meta-at", title="Original")
        old_updated = clip.updated_at

        # Change a metadata field (title) — NOT a content field
        clip.title = "New Title"
        store.update_clip(clip)

        fetched = store.get_clip("meta-at")
        assert fetched is not None
        assert fetched.updated_at == old_updated

    def test_status_change_bumps_updated_at(self, store) -> None:
        clip = _make_clip(store, id="status-at", status=ClipStatus.PENDING)
        old_updated = clip.updated_at

        clip.status = ClipStatus.DONE
        store.update_clip(clip)

        fetched = store.get_clip("status-at")
        assert fetched is not None
        assert fetched.updated_at > old_updated

    def test_resolution_change_bumps_updated_at(self, store) -> None:
        clip = _make_clip(store, id="res-at", resolution=(1920, 1080))
        old_updated = clip.updated_at

        clip.resolution = (2560, 1440)
        store.update_clip(clip)

        fetched = store.get_clip("res-at")
        assert fetched is not None
        assert fetched.updated_at > old_updated

# ---------------------------------------------------------------------------
# Spec 6 — _execute_with_retry
# ---------------------------------------------------------------------------

class TestExecuteWithRetry:
    def test_retry_on_database_locked(self, store) -> None:
        """_execute_with_retry should retry on SQLITE_BUSY and eventually succeed."""
        call_count = 0
        real_cur = store._conn.cursor()

        class FlakyCursor:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, params=()):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise sqlite3.OperationalError("database is locked")
                return self._real.execute(sql, params)

        flaky = FlakyCursor(real_cur)
        try:
            store._execute_with_retry(
                "INSERT INTO clips (id, stem, source_path, recorded_at) VALUES (?, ?, ?, ?)",
                ("retry-test", "retry", "/tmp/retry.mkv", "2026-01-01T00:00:00"),
                cursor=flaky,
            )
            store._conn.commit()
            assert call_count == 3
            fetched = store.get_clip("retry-test")
            assert fetched is not None
            assert fetched.stem == "retry"
        finally:
            store.delete_clip("retry-test", soft=False)

    def test_non_busy_error_reraised(self, store) -> None:
        """Non-SQLITE_BUSY OperationalErrors should be re-raised immediately."""

        class BadCursor:
            def execute(self, sql, params=()):
                raise sqlite3.OperationalError("no such table: fake")

        bad = BadCursor()
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            store._execute_with_retry("SELECT * FROM fake", cursor=bad)

# ---------------------------------------------------------------------------
# Cascading deletes
# ---------------------------------------------------------------------------

class TestCascadingDeletes:
    def test_delete_clip_cascades_to_tags(self, store: Store) -> None:
        """Soft-deleting a clip should not cascade-delete clip_tags rows."""
        clip = _make_clip(store, id="cascade-tag")
        store.set_tags(clip.id, ["frag", "ace"])
        store.delete_clip(clip.id, soft=True)

        # clip_tags should still exist (soft delete = NULL deleted_at)
        rows = store._read_conn.execute(
            "SELECT * FROM clip_tags WHERE clip_id = ?", ("cascade-tag",)
        ).fetchall()
        # Actually clip_tags has ON DELETE CASCADE, but soft delete doesn't
        # actually DELETE the row — it just sets deleted_at
        assert len(rows) == 2  # tags still associated after soft delete

    def test_hard_delete_cascades_to_edit_profiles(self, store: Store) -> None:
        """Hard-deleting a clip cascades to edit_profiles."""
        _make_clip(store, id="cascade-ep")
        ep = EditProfile(clip_id="cascade-ep", trim_start=2.0, trim_end=28.0)
        store.save_edit_profile(ep)

        store.delete_clip("cascade-ep", soft=False)
        assert store.get_edit_profile("cascade-ep") is None

    def test_hard_delete_cascades_to_url_history(self, store: Store) -> None:
        """Hard-deleting a clip cascades to url_history."""
        _make_clip(store, id="cascade-uh")
        store.insert_url_history("cascade-uh", "https://example.com/clip.mp4")

        store.delete_clip("cascade-uh", soft=False)
        history = store.get_url_history("cascade-uh")
        assert len(history) == 0

    def test_hard_delete_cascades_to_pip_cache(self, store: Store) -> None:
        """Hard-deleting a clip cascades to pip_cache."""
        _make_clip(store, id="cascade-pip")
        store._conn.execute(
            "INSERT INTO pip_cache (id, clip_id, start_offset, end_offset) VALUES (?, ?, 0.0, 30.0)",
            ("pip-test", "cascade-pip"),
        )
        store._conn.commit()

        store.delete_clip("cascade-pip", soft=False)
        row = store._read_conn.execute(
            "SELECT count(*) as cnt FROM pip_cache WHERE clip_id = ?", ("cascade-pip",)
        ).fetchone()
        assert row["cnt"] == 0

    def test_hard_delete_cascades_to_webhook_log(self, store: Store) -> None:
        """Hard-deleting a clip cascades to webhook_log."""
        _make_clip(store, id="cascade-wl")
        # Create a valid webhook first (webhook_log has FK to webhooks)
        wh = Webhook(id="wh-id", url="https://discord.com/api/webhooks/1/token", name="CascadeTest")
        store.save_webhook(wh)
        store._conn.execute(
            "INSERT INTO webhook_log (id, webhook_id, clip_id, success, status_code) VALUES (?, ?, ?, 1, 200)",
            ("wl-test", "wh-id", "cascade-wl"),
        )
        store._conn.commit()

        store.delete_clip("cascade-wl", soft=False)
        row = store._read_conn.execute(
            "SELECT count(*) as cnt FROM webhook_log WHERE clip_id = ?", ("cascade-wl",)
        ).fetchone()
        assert row["cnt"] == 0

# ---------------------------------------------------------------------------
# Foreign key enforcement
# ---------------------------------------------------------------------------

class TestForeignKeyEnforcement:
    def test_rejects_orphan_clip_tags(self, store: Store) -> None:
        """Inserting clip_tags for a nonexistent clip should fail."""
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO clip_tags (clip_id, tag_id) VALUES (?, ?)",
                ("nonexistent-clip", "nonexistent-tag"),
            )
            store._conn.commit()

    def test_rejects_orphan_edit_profile(self, store: Store) -> None:
        """Inserting edit_profile for a nonexistent clip should fail."""
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO edit_profiles (clip_id) VALUES (?)",
                ("nonexistent-clip",),
            )
            store._conn.commit()

    def test_rejects_orphan_webhook_log(self, store: Store) -> None:
        """Inserting webhook_log for a nonexistent webhook should fail."""
        _make_clip(store, id="orphan-wl-clip")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO webhook_log (id, webhook_id, clip_id, success, status_code) VALUES (?, ?, ?, 1, 200)",
                ("orphan-wl", "nonexistent-webhook", "orphan-wl-clip"),
            )
            store._conn.commit()

    def test_rejects_orphan_url_history(self, store: Store) -> None:
        """Inserting url_history for a nonexistent clip should fail."""
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO url_history (id, clip_id, url) VALUES (?, ?, ?)",
                ("orphan-uh", "nonexistent-clip", "https://example.com"),
            )
            store._conn.commit()

# ---------------------------------------------------------------------------
# Transaction rollback on error
# ---------------------------------------------------------------------------

class TestTransactionRollback:
    def test_insert_rolls_back_on_error(self, store: Store) -> None:
        """If an insert fails mid-transaction, prior changes are rolled back."""
        try:
            with store._base.tx() as cur:
                cur.execute(
                    "INSERT INTO clips (id, stem, source_path, recorded_at) VALUES (?, ?, ?, ?)",
                    ("rollback-test", "rollback", "/tmp/roll.mkv", "2026-01-01"),
                )
                # This will fail — the table doesn't exist
                cur.execute(
                    "INSERT INTO nonexistent_table (id) VALUES (?)",
                    ("x",),
                )
        except sqlite3.OperationalError:
            pass

        # Clip should NOT exist because the transaction was rolled back
        assert store.get_clip("rollback-test") is None

    def test_tx_context_rolls_back_on_exception(self, store: Store) -> None:
        """When tx() context manager exits with exception, changes are rolled back."""
        try:
            with store._base.tx() as cur:
                cur.execute(
                    "INSERT INTO clips (id, stem, source_path, recorded_at) VALUES (?, ?, ?, ?)",
                    ("tx-fail", "tx-fail", "/tmp/tx_fail.mkv", "2026-01-01"),
                )
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass

        assert store.get_clip("tx-fail") is None

# ---------------------------------------------------------------------------
# Duplicate key behavior
# ---------------------------------------------------------------------------

class TestDuplicateKey:
    def test_replaces_clip_on_same_id(self, store: Store) -> None:
        """INSERT OR REPLACE with same ID replaces the existing clip."""
        clip1 = _make_clip(store, id="dup-clip", title="Original", stem="original")
        clip2 = _make_clip(store, id="dup-clip", title="Replacement", stem="replacement")

        fetched = store.get_clip("dup-clip")
        assert fetched is not None
        assert fetched.title == "Replacement"
        assert fetched.stem == "replacement"

    def test_duplicate_task_id_replaced(self, store: Store) -> None:
        """INSERT OR REPLACE on tasks replaces existing task."""
        task1 = Task(id="dup-task", type=TaskKind.ENCODE, priority=1, payload={"clip_id": "c1"})
        store.insert_task(task1)

        task2 = Task(id="dup-task", type=TaskKind.UPLOAD, priority=5, payload={"clip_id": "c2"})
        store.insert_task(task2)

        pending = store.get_pending_tasks()
        matching = [t for t in pending if t.id == "dup-task"]
        assert len(matching) == 1
        assert matching[0].type == TaskKind.UPLOAD
        assert matching[0].priority == 5

    def test_duplicate_tag_name_replaced(self, store: Store) -> None:
        """INSERT OR IGNORE on tags with duplicate name does NOT replace."""
        # Tags use INSERT OR IGNORE with UNIQUE name constraint
        store._conn.execute(
            "INSERT INTO tags (id, name) VALUES (?, ?)",
            ("tag-v1", "clutch"),
        )
        store._conn.commit()

        # Insert with same name, different id — should be ignored
        store._conn.execute(
            "INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)",
            ("tag-v2", "clutch"),
        )
        store._conn.commit()

        row = store._read_conn.execute(
            "SELECT id FROM tags WHERE name = ?", ("clutch",)
        ).fetchone()
        assert row is not None
        assert row["id"] == "tag-v1"  # original preserved

# ---------------------------------------------------------------------------
# Empty trash edge cases
# ---------------------------------------------------------------------------

class TestEmptyTrash:
    def test_empty_trash_no_deleted_clips(self, store: Store) -> None:
        """empty_trash returns 0 when no clips are soft-deleted."""
        _make_clip(store, id="trash-nondel")
        count = store.empty_trash()
        assert count == 0
        assert store.get_clip("trash-nondel") is not None

    def test_empty_trash_only_removes_soft_deleted(self, store: Store) -> None:
        """empty_trash only removes clips with deleted_at set."""
        _make_clip(store, id="trash-keep")
        store.delete_clip("trash-keep", soft=True)
        _make_clip(store, id="trash-active")

        count = store.empty_trash()
        assert count == 1
        # Active clip should still exist
        assert store.get_clip("trash-active") is not None
        # Deleted clip should be gone
        assert store.get_clip("trash-keep") is None

    def test_empty_trash_twice_returns_zero(self, store: Store) -> None:
        """Calling empty_trash twice returns 0 the second time."""
        _make_clip(store, id="trash-double")
        store.delete_clip("trash-double", soft=True)
        count1 = store.empty_trash()
        assert count1 == 1
        count2 = store.empty_trash()
        assert count2 == 0

# ---------------------------------------------------------------------------
# Rate limiter edge cases
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_same_key_back_to_back_is_rate_limited(self, store: Store) -> None:
        """Two rapid calls for the same key should rate-limit."""
        r1 = store.check_persistent_rate("rate-test", interval_secs=60.0)
        assert r1 is None  # first call allowed
        r2 = store.check_persistent_rate("rate-test", interval_secs=60.0)
        assert r2 is not None  # second call blocked
        assert "wait" in r2.lower()

    def test_empty_key_does_not_raise(self, store: Store) -> None:
        """An empty string key should not cause errors."""
        result = store.check_persistent_rate("", interval_secs=10.0)
        assert result is None

    def test_long_key_does_not_raise(self, store: Store) -> None:
        """A very long key should not cause errors."""
        key = "k" * 1000
        result = store.check_persistent_rate(key, interval_secs=10.0)
        assert result is None

    def test_zero_interval_allows_all(self, store: Store) -> None:
        """Zero interval should never rate-limit."""
        for _ in range(10):
            result = store.check_persistent_rate("fast-key", interval_secs=0.0)
            assert result is None

# ---------------------------------------------------------------------------
# Spec 6 — Read-only connection
# ---------------------------------------------------------------------------

class TestReadOnlyConnection:
    def test_query_only_rejects_writes(self, store) -> None:
        """The read-only connection should reject write attempts."""
        with pytest.raises(sqlite3.OperationalError):
            store._read_conn.execute(
                "INSERT INTO clips (id, stem, source_path, recorded_at) VALUES (?, ?, ?, ?)",
                ("ro-test", "ro", "/tmp/ro.mkv", "2026-01-01T00:00:00"),
            )

    def test_read_conn_can_select(self, store) -> None:
        _make_clip(store, id="ro-select", title="Readable")
        row = store._read_conn.execute(
            "SELECT title FROM clips WHERE id = ?", ("ro-select",)
        ).fetchone()
        assert row is not None
        assert row["title"] == "Readable"

# ---------------------------------------------------------------------------
# Spec 6 — Retention helpers
# ---------------------------------------------------------------------------

class TestRetentionHelpers:
    def test_list_old_source_clips(self, store) -> None:
        from datetime import datetime, timezone
        old = datetime.now(timezone.utc) - timedelta(days=100)
        _make_clip(store, id="old-src", source_path="/tmp/old.mkv", recorded_at=old)
        _make_clip(store, id="new-src", source_path="/tmp/new.mkv")

        rows = store.list_old_source_clips(
            (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        )
        ids = {r["id"] for r in rows}
        assert "old-src" in ids
        assert "new-src" not in ids

    def test_batch_soft_delete(self, store) -> None:
        _make_clip(store, id="batch-1")
        _make_clip(store, id="batch-2")
        _make_clip(store, id="batch-3")

        count = store.batch_soft_delete_clips(["batch-1", "batch-2"])
        assert count == 2

        # get_clip does not filter deleted_at, so check the field directly
        assert store.get_clip("batch-1").deleted_at is not None
        assert store.get_clip("batch-2").deleted_at is not None
        assert store.get_clip("batch-3").deleted_at is None

    def test_has_active_task_for_clip(self, store) -> None:
        task = Task(
            id="t-active", type=TaskKind.ENCODE,
            payload={"clip_id": "task-clip"}, status=TaskStatus.PENDING,
        )
        store.insert_task(task)
        assert store.has_active_task_for_clip("task-clip") is True
        assert store.has_active_task_for_clip("no-task") is False

    def test_has_active_task_excludes_completed(self, store) -> None:
        task = Task(
            id="t-done", type=TaskKind.ENCODE,
            payload={"clip_id": "done-clip"}, status=TaskStatus.COMPLETED,
        )
        store.insert_task(task)
        assert store.has_active_task_for_clip("done-clip") is False


