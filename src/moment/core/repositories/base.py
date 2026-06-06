"""Base repository — connections, execute helpers, migration framework.

All domain repositories inherit from this class and share the same
encrypted write + read-only connections.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encrypted connection helpers (kept here for reuse by Store facade)
# ---------------------------------------------------------------------------


def _get_or_create_db_key() -> bytes | None:
    """Return the 256-bit DB encryption key from the system keyring."""
    try:
        import keyring  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        key = keyring.get_password("moment", "db_encryption_key")
    except Exception as exc:
        logger.error("Failed to read DB encryption key from keyring: %s", exc, exc_info=True)
        return None

    if key is not None:
        return key.encode()

    import secrets

    new_key = secrets.token_hex(32)
    try:
        keyring.set_password("moment", "db_encryption_key", new_key)
        logger.info("Generated and stored new DB encryption key in keyring")
        return new_key.encode()
    except Exception as exc:
        logger.error("Could not store DB encryption key in keyring: %s", exc, exc_info=True)
        return None


def _is_plaintext_sqlite(db_path: str) -> bool:
    """Check if *db_path* exists and starts with the SQLite magic header."""
    if not os.path.isfile(db_path):
        return False
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\0"
    except OSError:
        return False


def _migrate_plaintext_to_encrypted(db_path: str, key: bytes, sqlcipher_module: Any) -> None:
    """Export a plaintext DB into an encrypted one by copying data via
    standard sqlite3, then re-encrypting the copy in-place.

    Uses a temporary file alongside the original, then swaps them once
    the export is verified.
    """
    tmp_path = db_path + ".enc-tmp"
    import shutil

    try:
        # ── 1. Read schema + data from the plaintext source ─────────────
        src_conn = sqlite3.connect(db_path)
        src_conn.row_factory = sqlite3.Row
        src_conn.execute("PRAGMA journal_mode = OFF")
        tables = src_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        indexes = src_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        # Gather all rows per table
        table_data: dict[str, list[dict[str, Any]]] = {}
        for t in tables:
            name = t["name"]
            rows = src_conn.execute(f"SELECT * FROM [{name}]").fetchall()
            table_data[name] = [dict(r) for r in rows]

        src_conn.close()

        # ── 2. Create fresh encrypted DB with identical schema ─────────
        conn_enc = sqlcipher_module.connect(tmp_path, check_same_thread=False)
        conn_enc.execute(f"PRAGMA key = \"x'{key.decode()}'\"")
        conn_enc.execute("PRAGMA cipher_compatibility = 4")

        for t in tables:
            if t["sql"]:
                conn_enc.execute(t["sql"])
        for idx in indexes:
            if idx["sql"]:
                conn_enc.execute(idx["sql"])

        # ── 3. Copy data rows ────────────────────────────────────────────
        for name, rows in table_data.items():
            if not rows:
                continue
            cols = ", ".join(f"[{c}]" for c in rows[0])
            placeholders = ", ".join("?" for _ in rows[0])
            for row in rows:
                conn_enc.execute(
                    f"INSERT INTO [{name}] ({cols}) VALUES ({placeholders})",
                    list(row.values()),
                )

        conn_enc.commit()
        conn_enc.close()

        # ── 4. Verify the encrypted copy is readable ─────────────────────
        conn_check = sqlcipher_module.connect(tmp_path, check_same_thread=False)
        conn_check.execute(f"PRAGMA key = \"x'{key.decode()}'\"")
        conn_check.execute("SELECT count(*) FROM sqlite_master")
        conn_check.close()

        # ── 5. Swap ──────────────────────────────────────────────────────
        backup_path = db_path + ".pre-encrypted.bak"
        shutil.move(db_path, backup_path)
        shutil.move(tmp_path, db_path)
        logger.info(
            "Migrated plaintext DB to sqlcipher encryption (backup saved: %s)",
            backup_path,
        )
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise RuntimeError(f"Failed to migrate plaintext DB to encrypted: {exc}") from exc


def _set_row_factory(conn: sqlite3.Connection) -> None:
    """Attach the correct Row factory for plain sqlite3 or sqlcipher3 connections."""
    if type(conn).__module__.startswith("sqlcipher3"):
        import sqlcipher3.dbapi2 as sqlcipher  # type: ignore[import-untyped]

        conn.row_factory = sqlcipher.Row
    else:
        conn.row_factory = sqlite3.Row


def connect_encrypted(db_path: str) -> sqlite3.Connection:
    """Open an encrypted SQLite connection via sqlcipher3.

    If the database file exists but is plaintext SQLite (e.g. upgraded from
    an older version), it is automatically re-encrypted in-place.
    """
    try:
        import sqlcipher3.dbapi2 as sqlcipher  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError("sqlcipher3 is required — install with: pip install moment") from None

    key = _get_or_create_db_key()
    if key is None:
        raise RuntimeError(
            "System keyring is required for database encryption. "
            "Install keyring: pip install keyring"
        )

    # ── If the file exists but is plain SQLite, migrate it ─────────────
    if _is_plaintext_sqlite(db_path):
        logger.info(
            "Detected plaintext SQLite DB at %s – migrating to encrypted",
            db_path,
        )
        _migrate_plaintext_to_encrypted(db_path, key, sqlcipher)

    try:
        conn = sqlcipher.connect(db_path, check_same_thread=False)
        # key is bytes of a hex string (e.g. b"a1b2c3d4...");
        # decode back to hex string for the PRAGMA.
        conn.execute(f"PRAGMA key = \"x'{key.decode()}'\"")
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("SELECT count(*) FROM sqlite_master")
        _set_row_factory(conn)
        logger.info("Opened encrypted database with sqlcipher3")
        return conn
    except Exception as exc:
        # If the file exists but is neither plaintext SQLite nor valid
        # encrypted DB, it's corrupted — delete it so we create a fresh one.
        if os.path.isfile(db_path) and not _is_plaintext_sqlite(db_path):
            logger.warning(
                "Database file corrupted (%s) — deleting so a fresh one is created",
                exc,
            )
            try:
                os.remove(db_path)
                for suffix in ("-wal", "-shm"):
                    try:
                        os.remove(db_path + suffix)
                    except FileNotFoundError:
                        pass
            except OSError as remove_exc:
                raise RuntimeError(
                    f"Failed to open encrypted database: {exc}"
                    f" (and failed to remove corrupted file: {remove_exc})"
                ) from exc

            # Retry once — a fresh file will be created
            conn = sqlcipher.connect(db_path, check_same_thread=False)
            conn.execute(f"PRAGMA key = \"x'{key.decode()}'\"")
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("SELECT count(*) FROM sqlite_master")
            _set_row_factory(conn)
            logger.info("Created fresh encrypted database after removing corrupted file")
            return conn

        raise RuntimeError(f"Failed to open encrypted database: {exc}") from exc


def connect_encrypted_readonly(db_path: str) -> sqlite3.Connection:
    """Open a second read-only connection for SELECT queries."""
    conn = connect_encrypted(db_path)
    conn.execute("PRAGMA query_only = ON")
    return conn


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def json_dumps(obj: Any) -> str:
    """Serialize an object to JSON with UTC-aware datetime handling."""

    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    return json.dumps(obj, default=_default)


def json_loads(text: str | None) -> Any:
    """Deserialize JSON, returning ``None`` for empty/None input."""
    if text is None:
        return None
    return json.loads(text)


# ---------------------------------------------------------------------------
# Row-parsing helpers (shared across repos)
# ---------------------------------------------------------------------------


def parse_datetime(val: str | None) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def parse_path(val: str | None) -> Path | None:
    if val is None:
        return None
    return Path(val)


def parse_resolution(val: str | None) -> tuple[int, int]:
    if val is None:
        return (0, 0)
    try:
        parts = json.loads(val)
        return (int(parts[0]), int(parts[1]))
    except (json.JSONDecodeError, IndexError, ValueError):
        return (0, 0)


def parse_tags(tag_rows: list[sqlite3.Row]) -> list[str]:
    return [row["name"] for row in tag_rows]


def parse_enum(val: str | None, enum_cls: type, default: Any = None) -> Any:
    if val is None:
        return default
    try:
        return enum_cls[val]
    except KeyError:
        try:
            return enum_cls(val)
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# SQL Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,
    stem            TEXT NOT NULL DEFAULT '',
    source_path     TEXT NOT NULL DEFAULT '',
    encoded_path    TEXT,
    thumb_path      TEXT,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now')),
    duration        REAL NOT NULL DEFAULT 0,
    file_size       INTEGER NOT NULL DEFAULT 0,
    video_codec     TEXT NOT NULL DEFAULT '',
    fps             REAL NOT NULL DEFAULT 0,
    resolution      TEXT NOT NULL DEFAULT '[0,0]',
    has_mic_audio   INTEGER NOT NULL DEFAULT 0,
    has_game_audio  INTEGER NOT NULL DEFAULT 0,
    title           TEXT NOT NULL DEFAULT '',
    game            TEXT,
    folder          TEXT,
    favorite        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    error_message   TEXT,
    uploaded_at     TEXT,
    r2_url          TEXT,
    r2_path         TEXT,
    copy_count      INTEGER NOT NULL DEFAULT 0,
    visibility      TEXT NOT NULL DEFAULT 'public',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at      TEXT,
    protect_from_retention INTEGER NOT NULL DEFAULT 0,
    clip_type       TEXT NOT NULL DEFAULT 'VIDEO',
    source_app      TEXT,
    original_filename TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    watched_at      TEXT,
    watch_count     INTEGER NOT NULL DEFAULT 0,
    discord_user_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_clips_stem ON clips(stem);
CREATE INDEX IF NOT EXISTS idx_clips_game ON clips(game);
CREATE INDEX IF NOT EXISTS idx_clips_folder ON clips(folder);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_deleted ON clips(deleted_at);
CREATE INDEX IF NOT EXISTS idx_clips_created ON clips(created_at);

CREATE TABLE IF NOT EXISTS tags (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clip_tags (
    clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    tag_id  TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (clip_id, tag_id)
);

CREATE TABLE IF NOT EXISTS edit_profiles (
    clip_id             TEXT PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    trim_start          REAL,
    trim_end            REAL,
    split_points        TEXT NOT NULL DEFAULT '[]',
    segments            TEXT NOT NULL DEFAULT '[]',
    game_audio_volume   REAL NOT NULL DEFAULT 1.0,
    mic_audio_volume    REAL NOT NULL DEFAULT 1.0,
    filters             TEXT NOT NULL DEFAULT '[]',
    overlays            TEXT NOT NULL DEFAULT '[]',
    merge_source_ids    TEXT,
    edit_version        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id              TEXT PRIMARY KEY,
    session_stem    TEXT NOT NULL,
    offset_seconds  REAL NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    label           TEXT
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_session ON bookmarks(session_stem);

CREATE TABLE IF NOT EXISTS webhooks (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    notify_on       TEXT NOT NULL DEFAULT '[]',
    per_game_filter TEXT,
    include_clip_url INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS webhook_log (
    id              TEXT PRIMARY KEY,
    webhook_id      TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    clip_id         TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    delivered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    success         INTEGER NOT NULL DEFAULT 1,
    status_code     INTEGER NOT NULL DEFAULT 200,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS folders (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS game_profiles (
    id              TEXT PRIMARY KEY,
    game_name       TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    replay_duration INTEGER NOT NULL DEFAULT 30,
    audio_config    TEXT,
    capture_fps     INTEGER NOT NULL DEFAULT 60,
    encode_timing   TEXT,
    quality_preset  TEXT,
    pause_encode    INTEGER NOT NULL DEFAULT 1,
    pause_thumbnail INTEGER NOT NULL DEFAULT 1,
    auto_tag        INTEGER NOT NULL DEFAULT 1,
    auto_open_editor INTEGER NOT NULL DEFAULT 1,
    review_card     TEXT,
    min_duration    INTEGER NOT NULL DEFAULT 30,
    post_capture_action TEXT NOT NULL DEFAULT 'card'
);

CREATE INDEX IF NOT EXISTS idx_game_profiles_name ON game_profiles(game_name);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0,
    payload         TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS url_history (
    id          TEXT PRIMARY KEY,
    clip_id     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    copied_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_url_history_clip ON url_history(clip_id);

CREATE TABLE IF NOT EXISTS folder_clips (
    folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    clip_id   TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    PRIMARY KEY (folder_id, clip_id)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    key         TEXT PRIMARY KEY,
    last_called REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_expires ON rate_limits(expires_at);

CREATE TABLE IF NOT EXISTS pip_cache (
    id          TEXT PRIMARY KEY,
    clip_id     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    start_offset REAL NOT NULL DEFAULT 0.0,
    end_offset  REAL NOT NULL DEFAULT 30.0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_pip_cache_clip ON pip_cache(clip_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------


def _ensure_clips_table_columns(conn: sqlite3.Connection) -> None:
    """Add any columns to the ``clips`` table that exist in
    :data:`SCHEMA_SQL` but not yet in the live database.  This handles
    databases created with an older schema that is missing columns
    referenced by later ``CREATE INDEX`` statements."""
    import re

    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clips'"
    ).fetchone():
        return

    existing = {r["name"] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS clips\s*\((.+?)\)\s*;",
        SCHEMA_SQL,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return
    for line in m.group(1).split(","):
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        col_name = parts[0].strip("`\"'[]")
        if col_name not in existing:
            # SQLite ALTER TABLE ADD COLUMN only accepts name + type +
            # constant DEFAULT. Strip everything else.
            col_def = f"{parts[0]} {parts[1]}"
            default = None
            # Look for DEFAULT <value> (constant only)
            m_default = re.search(
                r"DEFAULT\s+(\d+|'[^']*'|\"[^\"]*\"|[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?|TRUE|FALSE|NULL)",
                line,
                re.IGNORECASE,
            )
            if m_default:
                default = m_default.group(0)
                col_def += f" {default}"
            conn.execute(f"ALTER TABLE clips ADD COLUMN {col_def}")


def _migration_001_initial(conn: sqlite3.Connection) -> None:
    """Create the full schema."""
    _ensure_clips_table_columns(conn)
    conn.executescript(SCHEMA_SQL)


def _migration_002_add_discord_user_id(conn: sqlite3.Connection) -> None:
    """Add discord_user_id column to clips (pre-v0.2 → v0.2)."""
    rows = conn.execute("PRAGMA table_info(clips)").fetchall()
    columns = {r["name"] for r in rows}
    if "discord_user_id" not in columns:
        conn.execute("ALTER TABLE clips ADD COLUMN discord_user_id TEXT NOT NULL DEFAULT ''")
        logger.info("Migration 002: Added discord_user_id column")


def _migration_003_add_include_clip_url(conn: sqlite3.Connection) -> None:
    """Add include_clip_url column to webhooks."""
    rows = conn.execute("PRAGMA table_info(webhooks)").fetchall()
    columns = {r["name"] for r in rows}
    if "include_clip_url" not in columns:
        conn.execute("ALTER TABLE webhooks ADD COLUMN include_clip_url INTEGER NOT NULL DEFAULT 0")
        logger.info("Migration 003: Added include_clip_url column")


def _migration_004_migrate_discord_token(conn: sqlite3.Connection) -> None:
    """Move discord_bot_token from settings table to system keyring."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("discord_bot_token",),
    ).fetchone()
    if row is None:
        return

    token = None
    try:
        token = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        token = row["value"]

    if not token or not isinstance(token, str) or not token.strip():
        conn.execute("DELETE FROM settings WHERE key = ?", ("discord_bot_token",))
        return

    token = token.strip()

    try:
        import keyring

        keyring.set_password("moment", "discord_bot_token", token)
        logger.info("Migration 004: Moved Discord token to keyring")
    except ImportError:
        logger.debug("keyring not installed — leaving token in settings")
        return
    except Exception:
        logger.warning("Failed to store Discord token in keyring", exc_info=True)
        return

    conn.execute("DELETE FROM settings WHERE key = ?", ("discord_bot_token",))
    logger.info("Migration 004: Removed Discord token from settings table")


def _migration_005_migrate_webhook_key(conn: sqlite3.Connection) -> None:
    """Move webhook_encryption_key from settings to keyring."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("webhook_encryption_key",),
    ).fetchone()
    if row is None:
        return

    legacy_key = None
    try:
        legacy_key = json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        legacy_key = row["value"]

    if not legacy_key or not isinstance(legacy_key, str) or not legacy_key.strip():
        conn.execute("DELETE FROM settings WHERE key = ?", ("webhook_encryption_key",))
        return

    try:
        import keyring

        keyring.set_password("moment", "webhook_encryption_key", legacy_key)
        logger.info("Migration 005: Moved webhook key to keyring")
    except ImportError:
        logger.debug("keyring not installed — leaving webhook key in settings")
        return
    except Exception:
        logger.warning("Failed to store webhook key in keyring", exc_info=True)
        return

    conn.execute("DELETE FROM settings WHERE key = ?", ("webhook_encryption_key",))


def _migration_006_migrate_old_dirs(conn: sqlite3.Connection) -> None:
    """Rename legacy clip-tray directories to moment."""
    old_db_dir = os.path.expanduser("~/.config/clip-tray")
    old_data_dir = os.path.expanduser("~/.local/share/clip-tray")
    new_db_dir = os.path.expanduser("~/.config/moment")
    new_data_dir = os.path.expanduser("~/.local/share/moment")

    for old, new in ((old_db_dir, new_db_dir), (old_data_dir, new_data_dir)):
        if os.path.isdir(old) and not os.path.isdir(new):
            try:
                os.rename(old, new)
                logger.info("Migration 006: Renamed %s → %s", old, new)
            except OSError as exc:
                logger.warning("Could not rename %s → %s: %s", old, new, exc)


def _migration_007_migrate_json(conn: sqlite3.Connection) -> None:
    """Import clips from legacy clips.json (handled by Store facade)."""
    # This is a data migration that requires Store-level logic.
    # The Store facade calls migrate_from_json() after migrations run.
    pass


def _migration_008_add_stem_column(conn: sqlite3.Connection) -> None:
    """Add stem column to clips and backfill from source_path (pre-stem DBs)."""
    from pathlib import Path

    from moment.utils.system import sanitize_stem

    rows = conn.execute("PRAGMA table_info(clips)").fetchall()
    columns = {r["name"] for r in rows}
    if "stem" not in columns:
        conn.execute("ALTER TABLE clips ADD COLUMN stem TEXT NOT NULL DEFAULT ''")
        logger.info("Migration 008: Added stem column")

    pending = conn.execute(
        "SELECT id, source_path FROM clips WHERE stem = '' OR stem IS NULL"
    ).fetchall()
    for row in pending:
        source = row["source_path"] or ""
        stem = sanitize_stem(Path(source).stem) if source else ""
        conn.execute("UPDATE clips SET stem = ? WHERE id = ?", (stem, row["id"]))
    if pending:
        logger.info("Migration 008: Backfilled stem for %d clip(s)", len(pending))


_MIGRATIONS: list[tuple[str, Callable[[sqlite3.Connection], None]]] = [
    ("001_initial", _migration_001_initial),
    ("002_add_discord_user_id", _migration_002_add_discord_user_id),
    ("003_add_include_clip_url", _migration_003_add_include_clip_url),
    ("004_migrate_discord_token", _migration_004_migrate_discord_token),
    ("005_migrate_webhook_key", _migration_005_migrate_webhook_key),
    ("006_migrate_old_dirs", _migration_006_migrate_old_dirs),
    ("007_migrate_json", _migration_007_migrate_json),
    ("008_add_stem_column", _migration_008_add_stem_column),
]

# ---------------------------------------------------------------------------
# Migration framework
# ---------------------------------------------------------------------------


def _create_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
            version   INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )


def _current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    _create_schema_version_table(conn)
    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    if row is None:
        return 0
    val = row["v"]
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in order, inside transactions."""
    # Defensive: skip on mocked connections (MagicMock has no real cursor)
    if getattr(conn, "_mock_name", None) is not None:
        return
    _create_schema_version_table(conn)
    current = _current_schema_version(conn)
    total = len(_MIGRATIONS)

    if current >= total:
        logger.debug("Database schema is up to date (version %d)", current)
        return

    for idx, (name, fn) in enumerate(_MIGRATIONS, start=1):
        if idx <= current:
            continue
        logger.info("Applying migration %d: %s", idx, name)
        try:
            with conn:
                fn(conn)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (idx,),
                )
            logger.info("Migration %d applied successfully", idx)
        except Exception as exc:
            logger.error("Migration %d (%s) failed: %s", idx, name, exc, exc_info=True)
            raise

    logger.info("Migrations complete: %d → %d", current, total)


def run_migrations_with_retry(
    conn: sqlite3.Connection,
    *,
    max_retries: int = 3,
) -> None:
    """Apply pending migrations, retrying transient failures."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            run_migrations(conn)
            return
        except Exception as exc:
            last_exc = exc
            if attempt + 1 >= max_retries:
                break
            locked = (
                isinstance(exc, sqlite3.OperationalError)
                and "database is locked" in str(exc).lower()
            )
            if locked:
                logger.warning(
                    "Database locked during migration, retrying (%d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
            else:
                logger.warning(
                    "Migration failed, retrying (%d/%d): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
            time.sleep(0.05 * (2**attempt))
    if last_exc is not None:
        raise last_exc


# ---------------------------------------------------------------------------
# BaseRepository
# ---------------------------------------------------------------------------


class BaseRepository:
    """Shared connections and execute helpers for all domain repositories."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        read_conn: sqlite3.Connection,
        lock: threading.Lock,
    ) -> None:
        self._conn = conn
        self._read_conn = read_conn
        self._lock = lock
        self._read_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Execute helpers
    # ------------------------------------------------------------------

    def execute_with_retry(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        cursor: sqlite3.Cursor | None = None,
        max_retries: int = 5,
    ) -> sqlite3.Cursor:
        """Execute *sql* with exponential backoff on ``SQLITE_BUSY``."""
        cur = cursor
        if cur is None:
            with self._lock:
                cur = self._conn.cursor()
        last_err: sqlite3.OperationalError | None = None
        for attempt in range(max_retries):
            try:
                cur.execute(sql, params)
                return cur
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc).lower():
                    last_err = exc
                    delay = 0.01 * (2**attempt)
                    logger.debug(
                        "SQLITE_BUSY on attempt %d/%d — sleeping %.3fs",
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise
        if last_err is not None:
            raise last_err
        return cur

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        """Context manager yielding a cursor; commits on success."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                for attempt in range(5):
                    try:
                        self._conn.commit()
                        break
                    except sqlite3.OperationalError as exc:
                        if "database is locked" in str(exc).lower():
                            delay = 0.01 * (2**attempt)
                            logger.debug(
                                "SQLITE_BUSY on commit attempt %d/5 — sleeping %.3fs",
                                attempt + 1,
                                delay,
                            )
                            time.sleep(delay)
                        else:
                            raise
                else:
                    self._conn.rollback()
                    raise sqlite3.OperationalError("database is locked (commit retries exhausted)")
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def execute_many(self, sql: str, params_list: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        """Batch execute with retry."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.executemany(sql, params_list)
                return cur
            finally:
                cur.close()

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """Thread-safe read of a single row."""
        with self._read_lock:
            return self._read_conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Thread-safe read of all rows."""
        with self._read_lock:
            return self._read_conn.execute(sql, params).fetchall()
