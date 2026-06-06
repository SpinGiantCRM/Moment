"""SQLite store — backward-compatible facade that delegates to domain repos.

The monolithic Store class has been refactored into repositories under
``moment.core.repositories``.  This module re-exports helpers and provides
a thin facade so existing callers continue to work without changes.

Store accepts an optional ``Config`` instance via its constructor, removing
the need for the module-level ``set_store_config()`` global.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import InvalidToken

from moment.core.encryption import (
    _fernet_lock,
    get_or_create_fernet,
    reset_fernet_cache,
    run_health_check,
)
from moment.core.migrations import OLD_JSON_PATH
from moment.core.models import Webhook
from moment.core.repositories.base import (
    BaseRepository,
    connect_encrypted,
    run_migrations_with_retry,
)
from moment.core.repositories.bookmark_repo import BookmarkRepository
from moment.core.repositories.clip_repo import ClipRepository
from moment.core.repositories.folder_repo import FolderRepository
from moment.core.repositories.profile_repo import ProfileRepository
from moment.core.repositories.settings_repo import SettingsRepository
from moment.core.repositories.tag_repo import TagRepository
from moment.core.repositories.task_repo import TaskRepository
from moment.core.repositories.webhook_repo import WebhookRepository

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

# Backward-compatible re-exports
_connect_encrypted = connect_encrypted

_OLD_DB_DIR = os.path.expanduser("~/.config/clip-tray")
_OLD_DATA_DIR = os.path.expanduser("~/.local/share/clip-tray")
_DEFAULT_DB_DIR = os.path.expanduser("~/.config/moment")
_DEFAULT_DATA_DIR = os.path.expanduser("~/.local/share/moment")
DB_PATH = os.path.join(_DEFAULT_DB_DIR, "clips.db")


class Store:
    """Thin facade — all CRUD logic lives in domain repos."""

    _fernet_lock = _fernet_lock
    _fernet_cache = None

    @staticmethod
    def _get_or_create_fernet():
        if Store._fernet_cache is not None:
            return Store._fernet_cache
        return get_or_create_fernet()

    @classmethod
    def reset_fernet_cache(cls):
        cls._fernet_cache = None
        reset_fernet_cache()

    def __init__(self, config: "Config | None" = None, db_path: str | None = None) -> None:
        """Args:
        config: Optional Config for path overrides.
        db_path: Explicit DB path (overrides Config and default).
        """
        self._config = config
        if db_path is not None:
            self._db_path = db_path
        elif config is not None:
            self._db_path = os.path.join(config.get_path("db_dir"), "clips.db")
        else:
            self._db_path = os.path.join(_DEFAULT_DB_DIR, "clips.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = _connect_encrypted(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        lock = threading.Lock()
        read_conn = _connect_encrypted(self._db_path)
        read_conn.execute("PRAGMA query_only = ON")
        if os.path.isfile(self._db_path):
            os.chmod(self._db_path, 0o600)
        self._base = BaseRepository(conn, read_conn, lock)
        self._conn = conn
        self._read_conn = read_conn
        self._lock = lock
        self.clips = ClipRepository(self._base)
        self.webhooks = WebhookRepository(self._base)
        self.profiles = ProfileRepository(self._base)
        self.tags = TagRepository(self._base)
        self.tasks = TaskRepository(self._base)
        self.folders = FolderRepository(self._base)
        self.bookmarks = BookmarkRepository(self._base)
        self.settings = SettingsRepository(self._base)
        self._run_encryption_health_check()
        run_migrations_with_retry(conn)
        self._migrate_old_dirs()
        self.migrate_from_json(Path(OLD_JSON_PATH))

    def close(self) -> None:
        for c in (self._conn, self._read_conn):
            try:
                c.close()
            except sqlite3.Error as exc:
                logger.warning("Failed to close database connection: %s", exc)

    def _execute_with_retry(self, sql, params=(), *, cursor=None, max_retries=5):
        return self._base.execute_with_retry(sql, params, cursor=cursor, max_retries=max_retries)

    def _tx(self):
        return self._base.tx()

    # -- Clips
    def insert_clip(self, clip):
        return self.clips.insert(clip)

    def get_clip(self, clip_id):
        return self.clips.get(clip_id)

    def update_clip(self, clip):
        return self.clips.update(clip)

    def delete_clip(self, clip_id, soft=True):
        return self.clips.delete(clip_id, soft=soft)

    def list_clips(self, **kwargs):
        return self.clips.list(**kwargs)

    def count_clips(self, **kwargs):
        return self.clips.count(**kwargs)

    # -- Tags
    def set_tags(self, clip_id, tags):
        self.tags.sync_for_clip(clip_id, tags)

    def list_tags(self, limit: int = 100, offset: int = 0):
        return self.tags.get_all(limit, offset)

    def delete_tag(self, tag_id):
        self.tags.delete(tag_id)

    # -- Edit profiles
    def get_edit_profile(self, clip_id):
        return self.profiles.get_edit_profile(clip_id)

    def save_edit_profile(self, profile):
        return self.profiles.save_edit_profile(profile)

    # -- Bookmarks
    def insert_bookmark(self, bm):
        return self.bookmarks.insert(bm)

    def get_bookmarks_for_session(self, session_stem):
        return self.bookmarks.get_for_session(session_stem)

    def delete_bookmark(self, bookmark_id):
        self.bookmarks.delete(bookmark_id)

    # -- Webhooks (Store handles Fernet)
    def save_webhook(self, wh):
        if "[REDACTED]" in wh.url:
            raise ValueError("Cannot save redacted webhook URL — provide the full HTTPS URL")
        if not wh.url.lower().strip().startswith("https://"):
            raise ValueError(f"Invalid webhook URL: must be HTTPS (got {wh.url[:30]})")
        try:
            fernet = self._get_or_create_fernet()
            encrypted = fernet.encrypt(wh.url.encode()).decode()
        except Exception as exc:
            logger.error("Webhook encryption failed: %s", exc)
            raise RuntimeError(f"Failed to encrypt webhook URL: {exc}") from exc
        raw = Webhook(
            id=wh.id,
            url=encrypted,
            name=wh.name,
            enabled=wh.enabled,
            notify_on=wh.notify_on,
            per_game_filter=wh.per_game_filter,
            include_clip_url=wh.include_clip_url,
        )
        self.webhooks.save(raw)
        return wh

    def list_webhooks(self):
        rows = self.webhooks.list_all()
        fernet = self._get_or_create_fernet()
        result = []
        for wh in rows:
            try:
                real_url = fernet.decrypt(wh.url.encode()).decode()
            except InvalidToken:
                raise RuntimeError(f"Failed to decrypt webhook URL for {wh.id}")
            m = re.match(r"(https://discord\.com/api/webhooks/\d+/)(.*)", real_url)
            if m:
                redacted = m.group(1) + "[REDACTED]"
            elif len(real_url) > 60:
                redacted = real_url[:57] + "..."
            else:
                redacted = real_url
            result.append(
                Webhook(
                    id=wh.id,
                    url=redacted,
                    name=wh.name,
                    enabled=wh.enabled,
                    notify_on=wh.notify_on,
                    per_game_filter=wh.per_game_filter,
                    include_clip_url=wh.include_clip_url,
                )
            )
        return result

    def get_webhook_url(self, webhook_id):
        stored = self.webhooks.get_raw_url(webhook_id)
        if stored is None:
            return None
        try:
            return self._get_or_create_fernet().decrypt(stored.encode()).decode()
        except InvalidToken:
            raise RuntimeError(f"Failed to decrypt webhook URL for {webhook_id}")

    def delete_webhook(self, webhook_id):
        self.webhooks.delete(webhook_id)

    def insert_webhook_log(self, entry):
        return self.webhooks.insert_log(entry)

    # -- Folders
    def save_folder(self, folder):
        return self.folders.save(folder)

    def list_folders(self, limit: int = 100, offset: int = 0):
        return self.folders.list_all(limit, offset)

    def delete_folder(self, folder_id):
        self.folders.delete(folder_id)

    # -- Game profiles
    def save_game_profile(self, profile):
        return self.profiles.save_game_profile(profile)

    def get_game_profile(self, game_name):
        return self.profiles.get_game_profile(game_name)

    def list_game_profiles(self, limit: int = 100, offset: int = 0):
        return self.profiles.list_game_profiles(limit, offset)

    def delete_game_profile(self, game_name):
        self.profiles.delete_game_profile(game_name)

    # -- Stats & logs
    def get_aggregate_stats(self):
        return self.clips.get_aggregate_stats()

    def list_webhook_logs(self, **kwargs):
        return self.webhooks.list_logs(**kwargs)

    def clear_webhook_logs(self):
        self.webhooks.clear_logs()

    def check_persistent_rate(self, key, interval_secs=60.0):
        return self.settings.check_rate(key, interval_secs)

    def get_webhook_log_count(self, *, webhook_id=None):
        return self.webhooks.get_log_count(webhook_id=webhook_id)

    # -- Trash
    def restore_clip(self, clip_id):
        return self.clips.restore(clip_id)

    def empty_trash(self):
        return self.clips.empty_trash()

    # -- URL history
    def insert_url_history(self, clip_id, url):
        self.clips.insert_url_history(clip_id, url)

    def get_url_history(self, clip_id):
        return self.clips.get_url_history(clip_id)

    # -- Tasks
    def insert_task(self, task):
        return self.tasks.insert(task)

    def get_pending_tasks(self, limit=10):
        return self.tasks.get_pending(limit)

    def update_task_status(self, task_id, status, error_message=None):
        self.tasks.update_status(task_id, status, error_message)

    # -- Retention helpers
    def list_old_source_clips(self, cutoff_iso, limit=100, offset=0):
        return self.clips.list_old_source_clips(cutoff_iso, limit, offset)

    def list_old_encoded_clips(self, cutoff_iso, limit=100, offset=0):
        return self.clips.list_old_encoded_clips(cutoff_iso, limit, offset)

    def list_uploaded_clips_oldest_first(self, limit=100, offset=0):
        return self.clips.list_uploaded_clips_oldest_first(limit, offset)

    def has_active_task_for_clip(self, clip_id):
        return self.clips.has_active_task_for_clip(clip_id)

    def batch_soft_delete_clips(self, clip_ids):
        return self.clips.batch_soft_delete(clip_ids)

    # -- Legacy delegates (kept for backward compat)
    def _migrate_old_dirs(self) -> None:
        """Delegate to migrations.migrate_old_dirs() with store constants."""
        from moment.core.migrations import migrate_old_dirs

        migrate_old_dirs(
            old_db_dir=_OLD_DB_DIR,
            old_data_dir=_OLD_DATA_DIR,
            new_db_dir=_DEFAULT_DB_DIR,
            new_data_dir=_DEFAULT_DATA_DIR,
        )

    def migrate_from_json(self, old_path) -> int:
        """Delegate to migrations.migrate_from_json()."""
        from moment.core.migrations import migrate_from_json

        return migrate_from_json(self, old_path)

    def _run_encryption_health_check(self) -> None:
        run_health_check(self._db_path)

    def _migrate_discord_user_id(self):
        pass

    def _migrate_webhook_include_url(self):
        pass
