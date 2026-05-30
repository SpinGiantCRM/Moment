"""SQLite store — all persistence for clips, profiles, tags, and config.

Uses WAL mode for concurrent access.  Handles JSON serialisation of
complex types (datetimes, Paths, lists, dicts) transparently.

Database path: ``~/.config/moment/clips.db``

The database is **always** encrypted at rest via ``pysqlcipher3`` with a
256-bit key stored in the system keyring.  Encryption is mandatory — the
store will not open without it.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

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
    OverlayConfig,
    ReviewCardConfig,
    SegmentEdit,
    Tag,
    Task,
    TaskKind,
    TaskStatus,
    Webhook,
    WebhookLogEntry,
)
from moment.utils.system import sanitize_stem

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encrypted connection — pysqlcipher3 (mandatory)
# ---------------------------------------------------------------------------


def _get_or_create_db_key() -> bytes | None:
    """Return the 256-bit DB encryption key from the system keyring.

    Generates and stores a new key on first access.  Returns ``None``
    if ``keyring`` is not installed or the keyring backend fails
    (caller must decide whether to hard-fail).
    """
    try:
        import keyring  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        key = keyring.get_password("moment", "db_encryption_key")
        if key is not None:
            return key.encode()
    except Exception:
        pass

    # Generate a new 256-bit key and persist it
    import secrets

    new_key = secrets.token_hex(32)  # 256 bits → 64 hex chars
    try:
        keyring.set_password("moment", "db_encryption_key", new_key)
        logger.info("Generated and stored new DB encryption key in keyring")
        return new_key.encode()
    except Exception as exc:
        logger.error("Could not store DB encryption key in keyring: %s", exc)
        return None


def _connect_encrypted(db_path: str) -> sqlite3.Connection:
    """Open the database with encryption via pysqlcipher3.

    Encryption is **mandatory** — pysqlcipher3 and keyring are required.
    Raises ``RuntimeError`` if any component is unavailable or fails.

    Args:
        db_path: Absolute path to the ``.db`` file.

    Returns:
        An encrypted ``sqlite3.Connection``.

    Raises:
        RuntimeError: If pysqlcipher3, keyring, or libsqlcipher are missing,
                      or the encrypted connection cannot be opened.
    """
    # 1. pysqlcipher3 is mandatory
    try:
        import pysqlcipher3.dbapi2 as sqlcipher  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "pysqlcipher3 is required — install with: pip install moment"
        ) from None

    # 2. DB encryption key from keyring (mandatory)
    key = _get_or_create_db_key()
    if key is None:
        raise RuntimeError(
            "System keyring is required for database encryption. "
            "Install keyring: pip install keyring"
        )

    # 3. Open with encryption
    try:
        conn = sqlcipher.connect(db_path, check_same_thread=False)
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        # Verify the key works by running a simple query
        conn.execute("SELECT count(*) FROM sqlite_master")
        logger.info("Opened encrypted database with pysqlcipher3")
        return conn
    except Exception as exc:
        raise RuntimeError(
            f"Failed to open encrypted database: {exc}"
        ) from exc

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_OLD_DB_DIR = os.path.expanduser("~/.config/clip-tray")
_OLD_DATA_DIR = os.path.expanduser("~/.local/share/clip-tray")
_DEFAULT_DB_DIR = os.path.expanduser("~/.config/moment")
_DEFAULT_DATA_DIR = os.path.expanduser("~/.local/share/moment")
DB_PATH = os.path.join(_DEFAULT_DB_DIR, "clips.db")
OLD_JSON_PATH = os.path.join(_DEFAULT_DB_DIR, "clips.json")
OLD_JSON_BAK = os.path.join(_DEFAULT_DB_DIR, "clips.json.bak")

_store_config: Config | None = None


def _get_config() -> Config | None:
    return _store_config


def set_store_config(config: Config | None) -> None:
    """Inject a Config instance so DB and data paths honour user overrides."""
    global _store_config
    _store_config = config


def get_db_dir() -> str:
    """Return the DB directory, respecting Config overrides."""
    cfg = _get_config()
    if cfg is not None:
        return cfg.get_path("db_dir")
    return _DEFAULT_DB_DIR


def get_data_dir() -> str:
    """Return the data directory, respecting Config overrides."""
    cfg = _get_config()
    if cfg is not None:
        return cfg.get_path("data_dir")
    return _DEFAULT_DATA_DIR


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _json_dumps(obj: Any) -> str:
    """Serialize an object to a JSON string with UTC-aware datetime handling."""
    def _default(o: Any) -> Any:
        if isinstance(o, (datetime,)):
            return o.isoformat()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
    return json.dumps(obj, default=_default)


def _json_loads(text: str | None) -> Any:
    """Deserialize a JSON string, returning ``None`` for empty/None input."""
    if text is None:
        return None
    return json.loads(text)


# ---------------------------------------------------------------------------
# Row ↔ dataclass converters
# ---------------------------------------------------------------------------

def _parse_datetime(val: str | None) -> datetime | None:
    if val is None:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def _parse_path(val: str | None) -> Path | None:
    if val is None:
        return None
    return Path(val)


def _parse_resolution(val: str | None) -> tuple[int, int]:
    if val is None:
        return (0, 0)
    try:
        parts = json.loads(val)
        return (int(parts[0]), int(parts[1]))
    except (json.JSONDecodeError, IndexError, ValueError):
        return (0, 0)


def _is_secure_url(url: str) -> bool:
    """Check that *url* is a valid HTTPS URL.

    Prevents accidental plaintext HTTP or unencrypted webhook targets
    that could leak clip data over the wire.
    """
    parsed = url.lower().strip()
    return parsed.startswith("https://")


def _parse_tags(tag_rows: list[sqlite3.Row]) -> list[str]:
    return [row["name"] for row in tag_rows]


def _parse_enum(val: str | None, enum_cls: type, default: Any = None) -> Any:
    if val is None:
        return default
    try:
        return enum_cls[val]
    except KeyError:
        try:
            return enum_cls(val)
        except ValueError:
            return default


def _row_to_clip(row: sqlite3.Row, tags: list[str] | None = None) -> Clip:
    return Clip(
        id=row["id"],
        stem=row["stem"],
        source_path=Path(row["source_path"]),
        encoded_path=_parse_path(row["encoded_path"]),
        thumb_path=_parse_path(row["thumb_path"]),
        recorded_at=_parse_datetime(row["recorded_at"]) or datetime.now(timezone.utc),
        duration=row["duration"] or 0.0,
        file_size=row["file_size"] or 0,
        video_codec=row["video_codec"] or "",
        fps=row["fps"] or 0.0,
        resolution=_parse_resolution(row["resolution"]),
        has_mic_audio=bool(row["has_mic_audio"]),
        has_game_audio=bool(row["has_game_audio"]),
        title=row["title"] or "",
        game=row["game"],
        tags=tags or [],
        folder=row["folder"],
        favorite=bool(row["favorite"]),
        status=_parse_enum(row["status"], ClipStatus, ClipStatus.PENDING),
        error_message=row["error_message"],
        uploaded_at=_parse_datetime(row["uploaded_at"]),
        r2_url=row["r2_url"],
        r2_path=row["r2_path"],
        copy_count=row["copy_count"] or 0,
        visibility=_parse_enum(row["visibility"], ClipVisibility, ClipVisibility.PUBLIC),
        created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
        deleted_at=_parse_datetime(row["deleted_at"]),
        protect_from_retention=bool(row["protect_from_retention"]),
        clip_type=_parse_enum(row["clip_type"], ClipType, ClipType.VIDEO),
        source_app=row["source_app"],
        original_filename=row["original_filename"],
        updated_at=_parse_datetime(row["updated_at"]) or datetime.now(timezone.utc),
        watched_at=_parse_datetime(row["watched_at"]),
        watch_count=row["watch_count"] or 0,
        discord_user_id=row["discord_user_id"] or "",
    )


def _clip_to_row(clip: Clip) -> dict[str, Any]:
    return {
        "id": clip.id,
        "stem": sanitize_stem(clip.stem),
        "source_path": str(clip.source_path),
        "encoded_path": str(clip.encoded_path) if clip.encoded_path else None,
        "thumb_path": str(clip.thumb_path) if clip.thumb_path else None,
        "recorded_at": clip.recorded_at.isoformat(),
        "duration": clip.duration,
        "file_size": clip.file_size,
        "video_codec": clip.video_codec,
        "fps": clip.fps,
        "resolution": json.dumps(list(clip.resolution)),
        "has_mic_audio": int(clip.has_mic_audio),
        "has_game_audio": int(clip.has_game_audio),
        "title": clip.title,
        "game": clip.game,
        "folder": clip.folder,
        "favorite": int(clip.favorite),
        "status": clip.status.name,
        "error_message": clip.error_message,
        "uploaded_at": clip.uploaded_at.isoformat() if clip.uploaded_at else None,
        "r2_url": clip.r2_url,
        "r2_path": clip.r2_path,
        "copy_count": clip.copy_count,
        "visibility": clip.visibility.value,
        "created_at": clip.created_at.isoformat(),
        "deleted_at": clip.deleted_at.isoformat() if clip.deleted_at else None,
        "protect_from_retention": int(clip.protect_from_retention),
        "clip_type": clip.clip_type.name,
        "source_app": clip.source_app,
        "original_filename": clip.original_filename,
        "updated_at": clip.updated_at.isoformat(),
        "watched_at": clip.watched_at.isoformat() if clip.watched_at else None,
        "watch_count": clip.watch_count,
        "discord_user_id": clip.discord_user_id,
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    """Persistence layer backed by SQLite in WAL mode."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, db_path: str | None = None) -> None:
        """Open (or create) the database and run migrations.

        Includes a startup encryption health-check that verifies:
        - pysqlcipher3 is importable (enforced by ``_connect_encrypted``)
        - Keyring is available (warning if not)
        - Fernet encrypt/decrypt round-trip works (hard fail if not)
        - DB file header integrity (warning if not encrypted)

        Args:
            db_path: Override the default database path (useful for testing).
        """
        self._db_path = db_path or os.path.join(get_db_dir(), "clips.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._conn = _connect_encrypted(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()

        # Restrict DB file to owner-only access (contains webhook URLs, config)
        if os.path.isfile(self._db_path):
            os.chmod(self._db_path, 0o600)

        # --- Startup encryption health-check ---
        self._run_encryption_health_check()

        # Migration: old clip-tray dirs → moment dirs (runs once)
        self._migrate_old_dirs()

        self._init_db()
        self._migrate_discord_user_id()
        self._migrate_json()
        self._migrate_discord_token()
        self._migrate_webhook_include_url()

    def _run_encryption_health_check(self) -> None:
        """Verify encryption components at startup.

        Checks:
            - pysqlcipher3 is importable (already enforced by ``_connect_encrypted``)
            - Keyring is available (warning if not)
            - Fernet encrypt/decrypt round-trip works (hard fail if not)
            - DB file header is not plaintext SQLite (warning if it looks unencrypted)

        Raises:
            RuntimeError: If the Fernet round-trip test fails.
        """
        # 1. Keyring availability check (warning only — DB key is more critical)
        try:
            import keyring  # noqa: F401
        except ImportError:
            logger.warning(
                "Keyring not available — webhook encryption and Discord token "
                "storage will be unavailable. Install with: pip install keyring"
            )

        # 2. Fernet encrypt/decrypt round-trip test
        try:
            from cryptography.fernet import Fernet

            test_key = Fernet.generate_key()
            fernet = Fernet(test_key)
            plaintext = b"moment-encryption-healthcheck"
            ciphertext = fernet.encrypt(plaintext)
            decrypted = fernet.decrypt(ciphertext)
            if decrypted != plaintext:
                raise RuntimeError("Fernet round-trip test failed")
            logger.debug("Fernet encrypt/decrypt round-trip OK")
        except Exception as exc:
            raise RuntimeError(
                f"Encryption health-check failed — Fernet not working: {exc}"
            ) from exc

        # 3. DB file header check (detect plaintext SQLite)
        if os.path.isfile(self._db_path) and os.path.getsize(self._db_path) > 0:
            with open(self._db_path, "rb") as fh:
                header = fh.read(16)
            # Standard SQLite3 header starts with "SQLite format 3\x00"
            if header.startswith(b"SQLite format 3\x00"):
                logger.warning(
                    "Database file appears to be plaintext SQLite — "
                    "expected SQLCipher-encrypted file. "
                    "If migrating from an older version, delete %s and restart "
                    "to create a new encrypted database.",
                    self._db_path,
                )
            else:
                logger.debug("Database file header OK (encrypted)")

    def _migrate_discord_token(self) -> None:
        """Move ``discord_bot_token`` from settings table to system keyring.

        Runs once per store open: reads the token from the ``settings``
        table, stores it in the OS keychain via ``keyring``, then deletes
        the row.  If ``keyring`` is not installed the token stays in the
        DB and a debug message is logged.
        """
        row = self._conn.execute(
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
            # Row exists but value is empty — just clean it up
            self._conn.execute(
                "DELETE FROM settings WHERE key = ?", ("discord_bot_token",)
            )
            self._conn.commit()
            return

        token = token.strip()

        try:
            import keyring

            keyring.set_password("moment", "discord_bot_token", token)
            logger.info("Migrated Discord bot token from settings to system keyring")
        except ImportError:
            logger.debug(
                "keyring not installed — leaving token in settings table"
            )
            return
        except Exception:
            logger.warning(
                "Failed to store Discord token in keyring — leaving in settings",
                exc_info=True,
            )
            return

        # Only delete from settings after successful keyring store
        self._conn.execute(
            "DELETE FROM settings WHERE key = ?", ("discord_bot_token",)
        )
        self._conn.commit()

    def _migrate_webhook_include_url(self) -> None:
        """Add ``include_clip_url`` column to webhooks table (pre-v0.3 migration)."""
        try:
            rows = self._conn.execute("PRAGMA table_info(webhooks)").fetchall()
            columns = {r["name"] for r in rows}
            if "include_clip_url" not in columns:
                self._conn.execute(
                    "ALTER TABLE webhooks ADD COLUMN include_clip_url INTEGER NOT NULL DEFAULT 0"
                )
                logger.info("Added include_clip_url column to webhooks table")
            self._conn.commit()
        except sqlite3.Error:
            pass

    def _migrate_discord_user_id(self) -> None:
        """Add ``discord_user_id`` column if it doesn't exist (pre-v0.2 migration)."""
        try:
            rows = self._conn.execute("PRAGMA table_info(clips)").fetchall()
            columns = {r["name"] for r in rows}
            if "discord_user_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE clips ADD COLUMN discord_user_id TEXT NOT NULL DEFAULT ''"
                )
                logger.info("Added discord_user_id column to clips table")
            self._conn.commit()
        except sqlite3.Error:
            pass

    def _migrate_old_dirs(self) -> None:
        """Migrate config & data from old ``clip-tray`` dirs to ``moment`` dirs.

        Runs once per user: when the old dir exists and the new one does not.
        Only runs when the default paths are in use (not user-overridden).
        """
        current_db_dir = get_db_dir()
        current_data_dir = get_data_dir()

        # Only migrate when using default paths (not overridden by user)
        if current_db_dir != _DEFAULT_DB_DIR or current_data_dir != _DEFAULT_DATA_DIR:
            return

        _rename_if_exists = {
            _OLD_DB_DIR: current_db_dir,
            _OLD_DATA_DIR: current_data_dir,
        }
        for old, new in _rename_if_exists.items():
            if os.path.isdir(old) and not os.path.isdir(new):
                try:
                    os.rename(old, new)
                    logger.info("Migrated %s → %s", old, new)
                except OSError:
                    logger.warning(
                        "Could not migrate %s → %s; will start fresh", old, new,
                    )

    def close(self) -> None:
        """Close the underlying connection."""
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        """Context manager that yields a cursor and commits on success.

        Acquires the write lock for the duration of the transaction.
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create all tables if they do not exist."""
        with self._tx() as cur:
            cur.executescript(_SCHEMA_SQL)

    def _migrate_json(self) -> None:
        """Import from old ``clips.json`` on first launch, then rename to ``.bak``."""
        self.migrate_from_json(Path(OLD_JSON_PATH))

    def migrate_from_json(self, old_path: Path) -> int:
        """Import clips from a legacy ``clips.json`` file.

        The file is renamed to ``.bak`` on success regardless of whether
        any clips were imported.

        Args:
            old_path: Path to the JSON file.

        Returns:
            Number of clips imported.
        """
        if not old_path.is_file():
            return 0

        # Only import if the clips table is empty
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()
        if row and row["cnt"] > 0:
            logger.info("%s found but DB already has data; renaming to .bak", old_path)
            try:
                os.rename(str(old_path), str(old_path) + ".bak")
            except OSError as exc:
                logger.warning("Could not rename %s: %s", old_path, exc)
            return 0

        logger.info("Migrating from %s → SQLite …", old_path)
        count = 0
        try:
            with open(old_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not parse %s: %s", old_path, exc)
            return 0

        entries: list[dict] = data if isinstance(data, list) else data.get("clips", [])
        for entry in entries:
            try:
                clip = Clip(
                    id=entry.get("id", str(uuid.uuid4())),
                    stem=entry.get("stem", ""),
                    source_path=Path(entry.get("source_path", "")),
                    recorded_at=_parse_datetime(entry.get("recorded_at")) or datetime.now(timezone.utc),
                    duration=float(entry.get("duration", 0)),
                    file_size=int(entry.get("file_size", 0)),
                    title=entry.get("title", ""),
                    game=entry.get("game"),
                    folder=entry.get("folder"),
                    favorite=bool(entry.get("favorite", False)),
                    status=_parse_enum(entry.get("status"), ClipStatus, ClipStatus.DONE),
                    visibility=_parse_enum(entry.get("visibility"), ClipVisibility, ClipVisibility.PUBLIC),
                    clip_type=ClipType.VIDEO,
                )
                self.insert_clip(clip)
                count += 1
            except Exception as exc:
                logger.warning("Skipping corrupt clip during migration: %s", exc)

        try:
            os.rename(str(old_path), str(old_path) + ".bak")
            logger.info("Migration complete: %d clips imported, old file → .bak", count)
        except OSError as exc:
            logger.warning("Could not rename %s: %s", old_path, exc)

        return count

    # ------------------------------------------------------------------
    # Clips CRUD
    # ------------------------------------------------------------------

    def insert_clip(self, clip: Clip) -> Clip:
        """Insert a new clip.  Returns the clip unchanged."""
        row = _clip_to_row(clip)
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        with self._tx() as cur:
            cur.execute(
                f"INSERT OR REPLACE INTO clips ({columns}) VALUES ({placeholders})",  # nosec
                list(row.values()),
            )
        return clip

    def get_clip(self, clip_id: str) -> Clip | None:
        """Return a single clip by id, or ``None``."""
        row = self._conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            return None
        tags = self._get_tags_for_clip(clip_id)
        return _row_to_clip(row, tags)

    def update_clip(self, clip: Clip) -> Clip:
        """Update an existing clip row."""
        clip.updated_at = datetime.now(timezone.utc)
        row = _clip_to_row(clip)
        set_clause = ", ".join(f"{k} = ?" for k in row)
        with self._tx() as cur:
            cur.execute(
                f"UPDATE clips SET {set_clause} WHERE id = ?",  # nosec
                list(row.values()) + [clip.id],
            )
        return clip

    def delete_clip(self, clip_id: str, soft: bool = True) -> bool:
        """Delete a clip.  Soft-delete by default (sets ``deleted_at`` and clears status)."""
        if soft:
            with self._tx() as cur:
                cur.execute(
                    "UPDATE clips SET deleted_at = ?, updated_at = ?, status = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), ClipStatus.DONE.name, clip_id),
                )
        else:
            with self._tx() as cur:
                cur.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        return True

    def _build_clip_where(
        self,
        *,
        status: ClipStatus | None = None,
        game: str | None = None,
        folder: str | None = None,
        favorite_only: bool = False,
        include_deleted: bool = False,
        clip_type: ClipType | None = None,
        search: str | None = None,
        tag: str | None = None,
        visibility: ClipVisibility | None = None,
        owner_id: str | None = None,
    ) -> tuple[str, list[Any]]:
        """Build a WHERE clause and parameter list for clip queries.

        Returns:
            A ``(where_clause, params)`` tuple.  The clause includes the
            leading ``WHERE`` keyword, or is empty if no filters apply.
        """
        where: list[str] = []
        params: list[Any] = []

        if not include_deleted:
            where.append("deleted_at IS NULL")
        if status is not None:
            where.append("status = ?")
            params.append(status.name)
        if game is not None:
            where.append("game = ?")
            params.append(game)
        if folder is not None:
            where.append("folder = ?")
            params.append(folder)
        if favorite_only:
            where.append("favorite = 1")
        if clip_type is not None:
            where.append("clip_type = ?")
            params.append(clip_type.name)
        if search is not None:
            where.append("(title LIKE ? OR stem LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if tag is not None:
            where.append(
                "id IN (SELECT clip_id FROM clip_tags ct JOIN tags t ON ct.tag_id = t.id WHERE t.name = ?)"
            )
            params.append(tag)

        # Visibility enforcement
        if visibility is not None:
            # Exact visibility filter (e.g. PUBLIC only for /recent)
            where.append("visibility = ?")
            params.append(visibility.value)
        elif owner_id == "*":
            # Admin/mutation-token caller — sees all clips, no filter
            pass
        elif owner_id is not None:
            # Owner sees: PUBLIC + UNLISTED + own PRIVATE clips
            # Guest sees: PUBLIC + UNLISTED only
            where.append(
                "(visibility IN (?, ?) OR (visibility = ? AND discord_user_id = ?))"
            )
            params.extend([
                ClipVisibility.PUBLIC.value,
                ClipVisibility.UNLISTED.value,
                ClipVisibility.PRIVATE.value,
                owner_id,
            ])
        else:
            # No owner context: exclude PRIVATE clips (default safe behavior)
            where.append("visibility != ?")
            params.append(ClipVisibility.PRIVATE.value)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        return where_clause, params

    def list_clips(
        self,
        *,
        status: ClipStatus | None = None,
        game: str | None = None,
        folder: str | None = None,
        favorite_only: bool = False,
        include_deleted: bool = False,
        clip_type: ClipType | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "-recorded_at",
        visibility: ClipVisibility | None = None,
        owner_id: str | None = None,
    ) -> list[Clip]:
        """Return a filtered, paged list of clips.

        Visibility filtering:
            - ``visibility=X`` returns only clips with that exact visibility.
            - ``owner_id=user`` returns PUBLIC + UNLISTED + PRIVATE clips
              owned by *user*.
            - Neither: excludes PRIVATE clips (safe guest default).
        """
        where_clause, params = self._build_clip_where(
            status=status,
            game=game,
            folder=folder,
            favorite_only=favorite_only,
            include_deleted=include_deleted,
            clip_type=clip_type,
            search=search,
            tag=tag,
            visibility=visibility,
            owner_id=owner_id,
        )
        # Parse sort_by: leading "-" means descending
        if sort_by.startswith("-"):
            sort_col = sort_by[1:]
            sort_dir = "DESC"
        else:
            sort_col = sort_by
            sort_dir = "ASC"
        # Whitelist sort columns to prevent injection
        _allowed_sorts = {
            "created_at", "updated_at", "recorded_at", "duration",
            "file_size", "title", "watch_count",
        }
        if sort_col not in _allowed_sorts:
            sort_col = "recorded_at"
            sort_dir = "DESC"

        query = (
            f"SELECT * FROM clips {where_clause} "  # nosec
            f"ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        clips: list[Clip] = []
        for row in rows:
            tags_list = self._get_tags_for_clip(row["id"])
            clips.append(_row_to_clip(row, tags_list))
        return clips

    def count_clips(
        self,
        *,
        status: ClipStatus | None = None,
        game: str | None = None,
        folder: str | None = None,
        favorite_only: bool = False,
        include_deleted: bool = False,
        clip_type: ClipType | None = None,
        search: str | None = None,
        tag: str | None = None,
        visibility: ClipVisibility | None = None,
        owner_id: str | None = None,
    ) -> int:
        """Return the number of clips matching filters."""
        where_clause, params = self._build_clip_where(
            status=status,
            game=game,
            folder=folder,
            favorite_only=favorite_only,
            include_deleted=include_deleted,
            clip_type=clip_type,
            search=search,
            tag=tag,
            visibility=visibility,
            owner_id=owner_id,
        )
        query = f"SELECT COUNT(*) as cnt FROM clips {where_clause}"  # nosec
        row = self._conn.execute(query, params).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _get_tags_for_clip(self, clip_id: str) -> list[str]:
        rows = self._conn.execute(
            """SELECT t.name FROM tags t
               JOIN clip_tags ct ON t.id = ct.tag_id
               WHERE ct.clip_id = ?""",
            (clip_id,),
        ).fetchall()
        return _parse_tags(rows)

    def _sync_tags(self, clip_id: str, tag_names: list[str]) -> None:
        """Replace all tag associations for *clip_id*."""
        with self._tx() as cur:
            cur.execute("DELETE FROM clip_tags WHERE clip_id = ?", (clip_id,))
            for name in tag_names:
                # Ensure the tag exists
                cur.execute(
                    "INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)",
                    (str(uuid.uuid4()), name),
                )
                # Link to clip
                tag_row = cur.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
                if tag_row:
                    cur.execute(
                        "INSERT OR IGNORE INTO clip_tags (clip_id, tag_id) VALUES (?, ?)",
                        (clip_id, tag_row["id"]),
                    )

    def set_tags(self, clip_id: str, tags: list[str]) -> None:
        """Atomic tag replacement for a clip."""
        self._sync_tags(clip_id, tags)

    def list_tags(self) -> list[Tag]:
        """Return all defined tags."""
        rows = self._conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [
            Tag(
                id=r["id"],
                name=r["name"],
                color=r["color"],
                created_at=_parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def delete_tag(self, tag_id: str) -> None:
        """Remove a tag and all its associations."""
        with self._tx() as cur:
            cur.execute("DELETE FROM clip_tags WHERE tag_id = ?", (tag_id,))
            cur.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    # ------------------------------------------------------------------
    # EditProfile
    # ------------------------------------------------------------------

    def get_edit_profile(self, clip_id: str) -> EditProfile | None:
        row = self._conn.execute(
            "SELECT * FROM edit_profiles WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            return None
        return EditProfile(
            clip_id=row["clip_id"],
            trim_start=row["trim_start"],
            trim_end=row["trim_end"],
            split_points=_json_loads(row["split_points"]) or [],
            segments=self._parse_segments(row["segments"]),
            game_audio_volume=row["game_audio_volume"],
            mic_audio_volume=row["mic_audio_volume"],
            filters=self._parse_filters(row["filters"]),
            overlays=self._parse_overlays(row["overlays"]),
            merge_source_ids=_json_loads(row["merge_source_ids"]),
            edit_version=row["edit_version"],
        )

    def save_edit_profile(self, profile: EditProfile) -> EditProfile:
        row = {
            "clip_id": profile.clip_id,
            "trim_start": profile.trim_start,
            "trim_end": profile.trim_end,
            "split_points": _json_dumps(profile.split_points),
            "segments": _json_dumps([s.__dict__ for s in profile.segments]),
            "game_audio_volume": profile.game_audio_volume,
            "mic_audio_volume": profile.mic_audio_volume,
            "filters": _json_dumps([f.__dict__ for f in profile.filters]),
            "overlays": _json_dumps([o.__dict__ for o in profile.overlays]),
            "merge_source_ids": _json_dumps(profile.merge_source_ids),
            "edit_version": profile.edit_version,
        }
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        with self._tx() as cur:
            cur.execute(
                f"INSERT OR REPLACE INTO edit_profiles ({columns}) VALUES ({placeholders})",  # nosec
                list(row.values()),
            )
        return profile

    # ------------------------------------------------------------------
    # Helpers for deserializing complex edit types
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_segments(raw: str | None) -> list[SegmentEdit]:
        data = _json_loads(raw) or []
        return [SegmentEdit(**s) for s in data if isinstance(s, dict)]

    @staticmethod
    def _parse_filters(raw: str | None) -> list[FilterConfig]:
        data = _json_loads(raw) or []
        return [FilterConfig(**f) for f in data if isinstance(f, dict)]

    @staticmethod
    def _parse_overlays(raw: str | None) -> list[OverlayConfig]:
        data = _json_loads(raw) or []
        return [OverlayConfig(**o) for o in data if isinstance(o, dict)]

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def insert_bookmark(self, bm: Bookmark) -> Bookmark:
        with self._tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO bookmarks
                   (id, session_stem, offset_seconds, created_at, label)
                   VALUES (?, ?, ?, ?, ?)""",
                (bm.id, bm.session_stem, bm.offset_seconds, bm.created_at.isoformat(), bm.label),
            )
        return bm

    def get_bookmarks_for_session(self, session_stem: str) -> list[Bookmark]:
        rows = self._conn.execute(
            "SELECT * FROM bookmarks WHERE session_stem = ? ORDER BY offset_seconds",
            (session_stem,),
        ).fetchall()
        return [
            Bookmark(
                id=r["id"],
                session_stem=r["session_stem"],
                offset_seconds=r["offset_seconds"],
                created_at=_parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
                label=r["label"],
            )
            for r in rows
        ]

    def delete_bookmark(self, bookmark_id: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Webhook encryption key (Fernet)
    # ------------------------------------------------------------------

    _fernet_lock: "threading.Lock" = threading.Lock()
    _fernet_cache: "Fernet | None" = None

    @staticmethod
    def _get_or_create_fernet() -> "Fernet":
        """Return a Fernet instance for webhook URL encryption.

        Key storage priority:
            1. In-memory class-level cache
            2. OS keyring (``moment_webhook_key``) — primary persistent store
            3. Config settings table (``webhook_encryption_key``) — legacy
               migration path; if found, moved to keyring and deleted from DB
            4. Generate a new key → store in keyring

        Thread-safe: uses a class-level lock to prevent duplicate key generation.

        Raises:
            RuntimeError: If the Fernet key cannot be created or accessed.
        """
        from cryptography.fernet import Fernet

        # Fast path: in-memory cache hit
        if Store._fernet_cache is not None:
            return Store._fernet_cache

        # Slow path: take lock
        with Store._fernet_lock:
            # Double-check after acquiring lock
            if Store._fernet_cache is not None:
                return Store._fernet_cache

            # 1. Try OS keyring (primary store)
            try:
                import keyring
                key_b64 = keyring.get_password("moment", "webhook_encryption_key")
                if key_b64:
                    fernet = Fernet(key_b64.encode())
                    Store._fernet_cache = fernet
                    return fernet
            except ImportError:
                raise RuntimeError(
                    "System keyring is required for webhook encryption. "
                    "Install keyring: pip install keyring"
                )
            except Exception as exc:
                logger.warning(
                    "Failed to read webhook key from keyring: %s", exc
                )

            # 2. Legacy migration: check settings table
            cfg = _get_config()
            if cfg is not None:
                legacy_key = cfg.get("webhook_encryption_key", None)
                if legacy_key:
                    logger.info("Migrating webhook encryption key to keyring")
                    fernet = Fernet(legacy_key.encode())
                    Store._fernet_cache = fernet
                    # Store in keyring and delete from settings table
                    try:
                        import keyring
                        keyring.set_password(
                            "moment", "webhook_encryption_key", legacy_key
                        )
                        cfg.delete("webhook_encryption_key")
                        logger.info(
                            "Webhook encryption key migrated to keyring and "
                            "removed from settings table"
                        )
                    except Exception as exc:
                        logger.warning(
                            "Migrated webhook key to memory but could not "
                            "persist to keyring: %s", exc
                        )
                    return fernet

            # 3. Generate new key → store in keyring (never in settings table)
            key = Fernet.generate_key()
            fernet = Fernet(key)
            Store._fernet_cache = fernet
            try:
                import keyring
                keyring.set_password(
                    "moment", "webhook_encryption_key", key.decode()
                )
                logger.info("Generated and stored new webhook encryption key in keyring")
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to persist webhook encryption key to keyring: {exc}"
                ) from exc
            return fernet

    @classmethod
    def reset_fernet_cache(cls) -> None:
        """Clear the in-memory Fernet cache (for test isolation)."""
        with cls._fernet_lock:
            cls._fernet_cache = None

    def save_webhook(self, wh: Webhook) -> Webhook:
        if not _is_secure_url(wh.url):
            raise ValueError(f"Invalid webhook URL: must be HTTPS (got {wh.url[:30]})")
        try:
            fernet = self._get_or_create_fernet()
            encrypted_url = fernet.encrypt(wh.url.encode()).decode()
        except Exception as exc:
            logger.error("Webhook encryption failed: %s", exc)
            raise RuntimeError(f"Failed to encrypt webhook URL: {exc}") from exc
        with self._tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO webhooks
                   (id, url, name, enabled, notify_on, per_game_filter, include_clip_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    wh.id, encrypted_url, wh.name,
                    int(wh.enabled),
                    _json_dumps(wh.notify_on),
                    _json_dumps(wh.per_game_filter),
                    int(wh.include_clip_url),
                ),
            )
        return wh

    @staticmethod
    def _redact_webhook_url(url: str) -> str:
        """Return a webhook URL with the token portion replaced by '[REDACTED]'."""
        import re
        m = re.match(r"(https://discord\.com/api/webhooks/\d+/)(.*)", url)
        if m:
            return m.group(1) + "[REDACTED]"
        # Fallback: try to decrypt, if it fails just truncate
        if len(url) > 60:
            return url[:57] + "..."
        return url

    def list_webhooks(self) -> list[Webhook]:
        rows = self._conn.execute("SELECT * FROM webhooks").fetchall()
        result: list[Webhook] = []
        for r in rows:
            stored = r["url"]
            from cryptography.fernet import InvalidToken
            fernet = self._get_or_create_fernet()
            try:
                real_url = fernet.decrypt(stored.encode()).decode()
            except InvalidToken:
                raise RuntimeError(
                    f"Failed to decrypt webhook URL for webhook {r['id']}: "
                    "key mismatch or legacy plaintext detected"
                )
            # Redact the token for display
            redacted = self._redact_webhook_url(real_url)
            result.append(Webhook(
                id=r["id"],
                url=redacted,
                name=r["name"] or "",
                enabled=bool(r["enabled"]),
                notify_on=_json_loads(r["notify_on"]) or [],
                per_game_filter=_json_loads(r["per_game_filter"]),
                include_clip_url=bool(r["include_clip_url"]),
            ))
        return result

    def get_webhook_url(self, webhook_id: str) -> str | None:
        """Return the decrypted (real) URL for a webhook, for dispatch use only.

        Raises:
            RuntimeError: If the URL cannot be decrypted.
        """
        row = self._conn.execute(
            "SELECT url FROM webhooks WHERE id = ?", (webhook_id,)
        ).fetchone()
        if row is None:
            return None
        stored = row["url"]
        from cryptography.fernet import InvalidToken
        fernet = self._get_or_create_fernet()
        try:
            return fernet.decrypt(stored.encode()).decode()
        except InvalidToken:
            raise RuntimeError(
                f"Failed to decrypt webhook URL for {webhook_id}: "
                "key mismatch or legacy plaintext detected"
            )

    def delete_webhook(self, webhook_id: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))

    def insert_webhook_log(self, entry: WebhookLogEntry) -> WebhookLogEntry:
        with self._tx() as cur:
            cur.execute(
                """INSERT INTO webhook_log
                   (id, webhook_id, clip_id, delivered_at, success, status_code, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id, entry.webhook_id, entry.clip_id,
                    entry.delivered_at.isoformat(),
                    int(entry.success), entry.status_code, entry.error_message,
                ),
            )
        return entry

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def save_folder(self, folder: Folder) -> Folder:
        with self._tx() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO folders (id, name, created_at) VALUES (?, ?, ?)",
                (folder.id, folder.name, folder.created_at.isoformat()),
            )
        return folder

    def list_folders(self) -> list[Folder]:
        rows = self._conn.execute("SELECT * FROM folders ORDER BY name").fetchall()
        return [
            Folder(
                id=r["id"],
                name=r["name"],
                created_at=_parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def delete_folder(self, folder_id: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    # ------------------------------------------------------------------
    # Game profiles
    # ------------------------------------------------------------------

    def save_game_profile(self, profile: GameProfile) -> GameProfile:
        review_card_json = (
            _json_dumps(profile.review_card.__dict__) if profile.review_card else None
        )
        with self._tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO game_profiles
                   (id, game_name, display_name, replay_duration, audio_config,
                    capture_fps, encode_timing, quality_preset, pause_encode,
                    pause_thumbnail, auto_tag, auto_open_editor, review_card,
                    min_duration, post_capture_action)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.id, profile.game_name, profile.display_name,
                    profile.replay_duration,
                    _json_dumps(profile.audio_config),
                    profile.capture_fps,
                    profile.encode_timing, profile.quality_preset,
                    int(profile.pause_encode), int(profile.pause_thumbnail),
                    int(profile.auto_tag), int(profile.auto_open_editor),
                    review_card_json,
                    profile.min_duration,
                    profile.post_capture_action,
                ),
            )
        return profile

    def get_game_profile(self, game_name: str) -> GameProfile | None:
        row = self._conn.execute(
            "SELECT * FROM game_profiles WHERE game_name = ?", (game_name,)
        ).fetchone()
        if row is None:
            return None
        review_card = None
        if row["review_card"]:
            rc_data = _json_loads(row["review_card"])
            if isinstance(rc_data, dict):
                review_card = ReviewCardConfig(**rc_data)
        return GameProfile(
            id=row["id"],
            game_name=row["game_name"],
            display_name=row["display_name"],
            replay_duration=row["replay_duration"],
            audio_config=_json_loads(row["audio_config"]),
            capture_fps=row["capture_fps"],
            encode_timing=row["encode_timing"],
            quality_preset=row["quality_preset"],
            pause_encode=bool(row["pause_encode"]),
            pause_thumbnail=bool(row["pause_thumbnail"]),
            auto_tag=bool(row["auto_tag"]),
            auto_open_editor=bool(row["auto_open_editor"]),
            review_card=review_card,
            min_duration=row["min_duration"],
            post_capture_action=row["post_capture_action"] or "card",
        )

    def list_game_profiles(self) -> list[GameProfile]:
        rows = self._conn.execute("SELECT * FROM game_profiles").fetchall()
        profiles: list[GameProfile] = []
        for r in rows:
            review_card = None
            if r["review_card"]:
                rc_data = _json_loads(r["review_card"])
                if isinstance(rc_data, dict):
                    review_card = ReviewCardConfig(**rc_data)
            profiles.append(GameProfile(
                id=r["id"],
                game_name=r["game_name"],
                display_name=r["display_name"],
                replay_duration=r["replay_duration"],
                audio_config=_json_loads(r["audio_config"]),
                capture_fps=r["capture_fps"],
                encode_timing=r["encode_timing"],
                quality_preset=r["quality_preset"],
                pause_encode=bool(r["pause_encode"]),
                pause_thumbnail=bool(r["pause_thumbnail"]),
                auto_tag=bool(r["auto_tag"]),
                auto_open_editor=bool(r["auto_open_editor"]),
                review_card=review_card,
                min_duration=r["min_duration"],
                post_capture_action=r["post_capture_action"] or "card",
            ))
        return profiles

    def delete_game_profile(self, game_name: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM game_profiles WHERE game_name = ?", (game_name,))

    # ------------------------------------------------------------------
    # Aggregate stats
    # ------------------------------------------------------------------

    def get_aggregate_stats(self) -> dict[str, Any]:
        """Return aggregate dashboard statistics.

        Returns a dict with:
            total_clips, total_storage_bytes, uploads_today, uploads_this_week,
            clips_per_game (list of {game, count, storage}),
            uploads_per_day (list of {date, count} for last 30 days),
            recent_uploads (last 10 uploaded clips as rows).
        """
        total = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM clips WHERE deleted_at IS NULL"
        ).fetchone()
        total_clips = total["cnt"] if total else 0

        storage = self._conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) as total FROM clips WHERE deleted_at IS NULL"
        ).fetchone()
        total_storage = storage["total"] if storage else 0

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        uploads_today_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM clips WHERE uploaded_at LIKE ? AND deleted_at IS NULL",
            (f"{today}%",),
        ).fetchone()
        uploads_today = uploads_today_row["cnt"] if uploads_today_row else 0

        uploads_week = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM clips WHERE uploaded_at >= date('now', '-7 days') AND deleted_at IS NULL"
        ).fetchone()
        uploads_this_week = uploads_week["cnt"] if uploads_week else 0

        # Clips per game (top 5 + "Other")
        game_rows = self._conn.execute(
            """SELECT COALESCE(game, 'Unknown') as game,
                      COUNT(*) as cnt,
                      COALESCE(SUM(file_size), 0) as storage
               FROM clips WHERE deleted_at IS NULL
               GROUP BY game ORDER BY cnt DESC"""
        ).fetchall()
        clips_per_game: list[dict[str, Any]] = [
            {"game": r["game"], "count": r["cnt"], "storage": r["storage"]}
            for r in game_rows
        ]

        # Uploads per day (last 30 days)
        day_rows = self._conn.execute(
            """SELECT date(created_at) as dt, COUNT(*) as cnt
               FROM clips WHERE deleted_at IS NULL
               AND created_at >= date('now', '-30 days')
               GROUP BY dt ORDER BY dt"""
        ).fetchall()
        uploads_per_day: list[dict[str, Any]] = [
            {"date": r["dt"], "count": r["cnt"]} for r in day_rows
        ]

        # Recent uploads (last 10)
        recent_rows = self._conn.execute(
            """SELECT title, game, uploaded_at, file_size, id
               FROM clips WHERE uploaded_at IS NOT NULL AND deleted_at IS NULL
               ORDER BY uploaded_at DESC LIMIT 10"""
        ).fetchall()
        recent_uploads: list[dict[str, Any]] = [
            {
                "id": r["id"],
                "title": r["title"],
                "game": r["game"],
                "uploaded_at": r["uploaded_at"],
                "file_size": r["file_size"],
            }
            for r in recent_rows
        ]

        return {
            "total_clips": total_clips,
            "total_storage_bytes": total_storage,
            "uploads_today": uploads_today,
            "uploads_this_week": uploads_this_week,
            "clips_per_game": clips_per_game,
            "uploads_per_day": uploads_per_day,
            "recent_uploads": recent_uploads,
        }

    # ------------------------------------------------------------------
    # Webhook logs
    # ------------------------------------------------------------------

    def list_webhook_logs(
        self,
        *,
        webhook_id: str | None = None,
        success: bool | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[WebhookLogEntry]:
        """Return webhook delivery log entries, newest first."""
        where: list[str] = []
        params: list[Any] = []
        if webhook_id is not None:
            where.append("webhook_id = ?")
            params.append(webhook_id)
        if success is not None:
            where.append("success = ?")
            params.append(1 if success else 0)
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM webhook_log {where_clause} ORDER BY delivered_at DESC LIMIT ? OFFSET ?",  # nosec
            params,
        ).fetchall()
        return [
            WebhookLogEntry(
                id=r["id"],
                webhook_id=r["webhook_id"],
                clip_id=r["clip_id"],
                delivered_at=_parse_datetime(r["delivered_at"]) or datetime.now(timezone.utc),
                success=bool(r["success"]),
                status_code=r["status_code"],
                error_message=r["error_message"],
            )
            for r in rows
        ]

    def clear_webhook_logs(self) -> None:
        """Delete all webhook log entries."""
        with self._tx() as cur:
            cur.execute("DELETE FROM webhook_log")

    # ------------------------------------------------------------------
    # Persistent rate limiting
    # ------------------------------------------------------------------

    def check_persistent_rate(
        self, key: str, interval_secs: float = 60.0
    ) -> str | None:
        """Persistent rate-limit check persisted in SQLite.

        Auto-cleans expired entries (older than *interval_secs* * 2).

        Args:
            key: Unique rate-limit key (e.g. truncated webhook hash).
            interval_secs: Minimum seconds between allowed calls.

        Returns:
            An error message if rate-limited, or ``None`` if allowed.
        """
        import time

        now = time.time()
        expire_before = now - (interval_secs * 2)

        with self._lock:
            # Auto-clean expired entries
            self._conn.execute(
                "DELETE FROM rate_limits WHERE expires_at < ?",
                (expire_before,),
            )
            self._conn.commit()

            # Check existing entry
            row = self._conn.execute(
                "SELECT last_called FROM rate_limits WHERE key = ?", (key,)
            ).fetchone()

            if row is not None:
                elapsed = now - row["last_called"]
                if elapsed < interval_secs:
                    wait = int(interval_secs - elapsed + 1)
                    return f"Please wait {wait} seconds before trying again"
                # Update existing entry
                self._conn.execute(
                    "UPDATE rate_limits SET last_called = ?, expires_at = ? WHERE key = ?",
                    (now, now + interval_secs, key),
                )
            else:
                # Insert new entry
                self._conn.execute(
                    "INSERT OR REPLACE INTO rate_limits (key, last_called, expires_at) VALUES (?, ?, ?)",
                    (key, now, now + interval_secs),
                )
            self._conn.commit()
            return None

    def get_webhook_log_count(self, *, webhook_id: str | None = None) -> int:
        """Return total number of webhook log entries."""
        if webhook_id is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM webhook_log WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM webhook_log").fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Trash operations
    # ------------------------------------------------------------------

    def restore_clip(self, clip_id: str) -> bool:
        """Restore a soft-deleted clip by clearing ``deleted_at``.

        Returns ``True`` if a row was modified, ``False`` if the clip
        was not found or was not deleted.
        """
        with self._tx() as cur:
            cur.execute(
                "UPDATE clips SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL",
                (datetime.now(timezone.utc).isoformat(), clip_id),
            )
            return cur.rowcount > 0

    def empty_trash(self) -> int:
        """Permanently delete all soft-deleted clips.

        Returns the number of clips removed.
        """
        with self._tx() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM clips WHERE deleted_at IS NOT NULL")
            count = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM clips WHERE deleted_at IS NOT NULL")
            return count

    # ------------------------------------------------------------------
    # URL History
    # ------------------------------------------------------------------

    def insert_url_history(self, clip_id: str, url: str) -> None:
        """Record that *url* was copied for *clip_id*."""
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO url_history (id, clip_id, url) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), clip_id, url),
            )

    def get_url_history(self, clip_id: str) -> list[dict[str, Any]]:
        """Return URL copy history for *clip_id*, most recent first."""
        rows = self._conn.execute(
            "SELECT url, copied_at FROM url_history WHERE clip_id = ? ORDER BY copied_at DESC",
            (clip_id,),
        ).fetchall()
        return [{"url": r["url"], "copied_at": r["copied_at"]} for r in rows]

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def insert_task(self, task: Task) -> Task:
        with self._tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO tasks
                   (id, type, priority, payload, status, created_at,
                    retry_count, max_retries, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id, task.type.value, task.priority,
                    _json_dumps(task.payload), task.status.name,
                    task.created_at.isoformat(), task.retry_count,
                    task.max_retries, task.error_message,
                ),
            )
        return task

    def get_pending_tasks(self, limit: int = 10) -> list[Task]:
        rows = self._conn.execute(
            """SELECT * FROM tasks WHERE status = 'PENDING'
               ORDER BY priority DESC, created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            Task(
                id=r["id"],
                type=TaskKind(r["type"]),
                priority=r["priority"],
                payload=_json_loads(r["payload"]) or {},
                status=TaskStatus[r["status"]],
                created_at=_parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
                retry_count=r["retry_count"],
                max_retries=r["max_retries"],
                error_message=r["error_message"],
            )
            for r in rows
        ]

    def update_task_status(
        self, task_id: str, status: TaskStatus, error_message: str | None = None
    ) -> None:
        with self._tx() as cur:
            cur.execute(
                """UPDATE tasks SET status = ?, error_message = ?,
                   retry_count = retry_count + 1 WHERE id = ?""",
                (status.name, error_message, task_id),
            )


# ---------------------------------------------------------------------------
# SQL Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
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
