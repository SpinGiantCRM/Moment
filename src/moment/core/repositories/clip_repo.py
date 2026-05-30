"""Clip repository — all clip persistence and queries."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moment.core.models import (
    Clip,
    ClipStatus,
    ClipType,
    ClipVisibility,
)
from moment.core.repositories.base import (
    BaseRepository,
    json_dumps,
    json_loads,
    parse_datetime,
    parse_enum,
    parse_path,
    parse_resolution,
    parse_tags,
)
from moment.utils.system import sanitize_stem

logger = logging.getLogger(__name__)

# Content fields that bump updated_at on change
_CONTENT_FIELDS: frozenset[str] = frozenset({
    "source_path", "file_size", "status", "encoded_path",
    "thumb_path", "r2_url", "duration", "resolution",
})


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
        "resolution": json_dumps(list(clip.resolution)),
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


# -- Projected column sets for shape-based queries ---------------------------

#: Columns for grid/list views (19 columns).  Includes every field
#: that ClipDelegate.build_item_data and common list callers access.
_LIST_COLUMNS: str = (
    "id, stem, title, game, duration, file_size, status, favorite, "
    "thumb_path, encoded_path, r2_url, created_at, updated_at, recorded_at, "
    "visibility, clip_type, deleted_at, resolution, fps"
)

#: Columns for stats-only queries (aggregation by game/storage)
_STATS_COLUMNS: str = "id, file_size, status, recorded_at, game"


def _row_to_clip(row: Any, tags: list[str] | None = None) -> Clip:
    """Convert a DB row (sqlite3.Row or dict) to a Clip, tolerant of missing
    columns (returns defaults for any column not present in the SELECT)."""
    def _get(key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError):
            return default

    return Clip(
        id=_get("id", ""),
        stem=_get("stem", ""),
        source_path=Path(_get("source_path", ".")),
        encoded_path=parse_path(_get("encoded_path")),
        thumb_path=parse_path(_get("thumb_path")),
        recorded_at=parse_datetime(_get("recorded_at")) or datetime.now(timezone.utc),
        duration=_get("duration") or 0.0,
        file_size=_get("file_size") or 0,
        video_codec=_get("video_codec") or "",
        fps=_get("fps") or 0.0,
        resolution=parse_resolution(_get("resolution")),
        has_mic_audio=bool(_get("has_mic_audio")),
        has_game_audio=bool(_get("has_game_audio")),
        title=_get("title") or "",
        game=_get("game"),
        tags=tags or [],
        folder=_get("folder"),
        favorite=bool(_get("favorite")),
        status=parse_enum(_get("status"), ClipStatus, ClipStatus.PENDING),
        error_message=_get("error_message"),
        uploaded_at=parse_datetime(_get("uploaded_at")),
        r2_url=_get("r2_url"),
        r2_path=_get("r2_path"),
        copy_count=_get("copy_count") or 0,
        visibility=parse_enum(_get("visibility"), ClipVisibility, ClipVisibility.PUBLIC),
        created_at=parse_datetime(_get("created_at")) or datetime.now(timezone.utc),
        deleted_at=parse_datetime(_get("deleted_at")),
        protect_from_retention=bool(_get("protect_from_retention")),
        clip_type=parse_enum(_get("clip_type"), ClipType, ClipType.VIDEO),
        source_app=_get("source_app"),
        original_filename=_get("original_filename"),
        updated_at=parse_datetime(_get("updated_at")) or datetime.now(timezone.utc),
        watched_at=parse_datetime(_get("watched_at")),
        watch_count=_get("watch_count") or 0,
        discord_user_id=_get("discord_user_id") or "",
    )


class ClipRepository(BaseRepository):
    """All persistence for clips and clip-derived queries."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def insert(self, clip: Clip) -> Clip:
        row = _clip_to_row(clip)
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        with self.tx() as cur:
            cur.execute(
                f"INSERT OR REPLACE INTO clips ({columns}) VALUES ({placeholders})",  # nosec
                list(row.values()),
            )
        return clip

    def get(self, clip_id: str, tags: list[str] | None = None) -> Clip | None:
        row = self._read_conn.execute(
            "SELECT * FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            return None
        if tags is None:
            tags = self._get_tags_for_clip(clip_id)
        return _row_to_clip(row, tags)

    def update(self, clip: Clip) -> Clip:
        old = self.get(clip.id)
        if old is not None:
            changed = any(
                getattr(old, f) != getattr(clip, f)
                for f in _CONTENT_FIELDS
            )
            if changed:
                clip.updated_at = datetime.now(timezone.utc)
            else:
                clip.updated_at = old.updated_at
        else:
            clip.updated_at = datetime.now(timezone.utc)
        row = _clip_to_row(clip)
        set_clause = ", ".join(f"{k} = ?" for k in row)
        with self.tx() as cur:
            cur.execute(
                f"UPDATE clips SET {set_clause} WHERE id = ?",  # nosec
                list(row.values()) + [clip.id],
            )
        return clip

    def delete(self, clip_id: str, *, soft: bool = True) -> bool:
        if soft:
            with self.tx() as cur:
                cur.execute(
                    """UPDATE clips
                        SET deleted_at = ?, updated_at = ?, status = ?
                        WHERE id = ?""",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                        ClipStatus.DONE.name,
                        clip_id,
                    ),
                )
        else:
            with self.tx() as cur:
                cur.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        return True

    def restore(self, clip_id: str) -> bool:
        with self.tx() as cur:
            cur.execute(
                """UPDATE clips
                    SET deleted_at = NULL, updated_at = ?
                    WHERE id = ? AND deleted_at IS NOT NULL""",
                (datetime.now(timezone.utc).isoformat(), clip_id),
            )
            return cur.rowcount > 0

    def empty_trash(self) -> int:
        with self.tx() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM clips WHERE deleted_at IS NOT NULL")
            count = cur.fetchone()["cnt"]
            cur.execute("DELETE FROM clips WHERE deleted_at IS NOT NULL")
            return count

    # ------------------------------------------------------------------
    # Tags (internal — used by get() when tags not provided)
    # ------------------------------------------------------------------

    def _get_tags_for_clip(self, clip_id: str) -> list[str]:
        rows = self._read_conn.execute(
            """SELECT t.name FROM tags t
               JOIN clip_tags ct ON t.id = ct.tag_id
               WHERE ct.clip_id = ?""",
            (clip_id,),
        ).fetchall()
        return parse_tags(rows)

    def sync_tags(self, clip_id: str, tag_names: list[str]) -> None:
        """Replace all tag associations for a clip."""
        with self.tx() as cur:
            cur.execute("DELETE FROM clip_tags WHERE clip_id = ?", (clip_id,))
            for name in tag_names:
                cur.execute(
                    "INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)",
                    (str(uuid.uuid4()), name),
                )
                tag_row = cur.execute(
                    "SELECT id FROM tags WHERE name = ?", (name,)
                ).fetchone()
                if tag_row:
                    cur.execute(
                        "INSERT OR IGNORE INTO clip_tags (clip_id, tag_id) VALUES (?, ?)",
                        (clip_id, tag_row["id"]),
                    )

    # ------------------------------------------------------------------
    # Listing / filtering
    # ------------------------------------------------------------------

    def _build_where(
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
                """id IN (
                    SELECT clip_id FROM clip_tags ct
                    JOIN tags t ON ct.tag_id = t.id
                    WHERE t.name = ?
                )"""
            )
            params.append(tag)

        if visibility is not None:
            where.append("visibility = ?")
            params.append(visibility.value)
        elif owner_id == "*":
            pass
        elif owner_id is not None:
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
            where.append("visibility != ?")
            params.append(ClipVisibility.PRIVATE.value)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        return where_clause, params

    def list(
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
        shape: str = "list",
    ) -> list[Clip]:
        """List clips with optional filters and pagination.

        Args:
            shape: One of ``"list"`` (projected columns, default),
                ``"detail"`` (SELECT *), ``"stats"`` (minimal columns).
                ``"list"`` is sufficient for grid views and card delegates.
        """
        where_clause, params = self._build_where(
            status=status, game=game, folder=folder,
            favorite_only=favorite_only, include_deleted=include_deleted,
            clip_type=clip_type, search=search, tag=tag,
            visibility=visibility, owner_id=owner_id,
        )
        if sort_by.startswith("-"):
            sort_col = sort_by[1:]
            sort_dir = "DESC"
        else:
            sort_col = sort_by
            sort_dir = "ASC"
        _allowed_sorts = {
            "created_at", "updated_at", "recorded_at", "duration",
            "file_size", "title", "watch_count",
        }
        if sort_col not in _allowed_sorts:
            sort_col = "recorded_at"
            sort_dir = "DESC"

        # Projected columns per shape
        if shape == "stats":
            columns = _STATS_COLUMNS
        elif shape == "detail":
            columns = "*"
        else:
            columns = _LIST_COLUMNS

        query = (
            f"SELECT {columns} FROM clips {where_clause} "  # nosec
            f"ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = self._read_conn.execute(query, params).fetchall()
        clips: list[Clip] = []
        for row in rows:
            tags = self._get_tags_for_clip(row["id"])
            clips.append(_row_to_clip(row, tags))
        return clips

    def count(
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
        where_clause, params = self._build_where(
            status=status, game=game, folder=folder,
            favorite_only=favorite_only, include_deleted=include_deleted,
            clip_type=clip_type, search=search, tag=tag,
            visibility=visibility, owner_id=owner_id,
        )
        query = f"SELECT COUNT(*) as cnt FROM clips {where_clause}"  # nosec
        row = self._read_conn.execute(query, params).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Aggregate stats
    # ------------------------------------------------------------------

    def get_aggregate_stats(self) -> dict[str, Any]:
        # Query 1: Total counts + today + this week (single query)
        totals = self._read_conn.execute(
            """SELECT COUNT(*) as total_clips,
                      COALESCE(SUM(file_size), 0) as total_storage_bytes,
                      COUNT(*) FILTER (
                          WHERE uploaded_at >= datetime('now', '-1 day')
                      ) as uploads_today,
                      COUNT(*) FILTER (
                          WHERE uploaded_at >= datetime('now', '-7 days')
                      ) as uploads_this_week
               FROM clips WHERE deleted_at IS NULL"""
        ).fetchone()

        # Query 2: Per-game breakdown (top 20 by count)
        game_rows = self._read_conn.execute(
            """SELECT COALESCE(game, 'Unknown') as game,
                      COUNT(*) as cnt,
                      COALESCE(SUM(file_size), 0) as storage
               FROM clips WHERE deleted_at IS NULL
               GROUP BY game ORDER BY cnt DESC LIMIT 20"""
        ).fetchall()

        # Query 3: 30-day upload history
        day_rows = self._read_conn.execute(
            """SELECT date(created_at) as dt, COUNT(*) as cnt
               FROM clips WHERE deleted_at IS NULL
               AND created_at >= date('now', '-30 days')
               GROUP BY dt ORDER BY dt"""
        ).fetchall()

        # Recent uploads (bonus — already a single query)
        recent_rows = self._read_conn.execute(
            """SELECT title, game, uploaded_at, file_size, id
               FROM clips WHERE uploaded_at IS NOT NULL AND deleted_at IS NULL
               ORDER BY uploaded_at DESC LIMIT 10"""
        ).fetchall()

        return {
            "total_clips": totals["total_clips"] if totals else 0,
            "total_storage_bytes": totals["total_storage_bytes"] if totals else 0,
            "uploads_today": totals["uploads_today"] if totals else 0,
            "uploads_this_week": totals["uploads_this_week"] if totals else 0,
            "clips_per_game": [
                {"game": r["game"], "count": r["cnt"], "storage": r["storage"]}
                for r in game_rows
            ],
            "uploads_per_day": [
                {"date": r["dt"], "count": r["cnt"]} for r in day_rows
            ],
            "recent_uploads": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "game": r["game"],
                    "uploaded_at": r["uploaded_at"],
                    "file_size": r["file_size"],
                }
                for r in recent_rows
            ],
        }

    # ------------------------------------------------------------------
    # Retention helpers
    # ------------------------------------------------------------------

    def list_old_source_clips(
        self, cutoff_iso: str, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        return self._read_conn.execute(
            """SELECT id, source_path, stem, recorded_at,
                      protect_from_retention, status
               FROM clips
               WHERE recorded_at < ?
                 AND source_path IS NOT NULL
                 AND source_path != ''
                 AND deleted_at IS NULL
               ORDER BY recorded_at ASC
               LIMIT ? OFFSET ?""",
            (cutoff_iso, limit, offset),
        ).fetchall()

    def list_old_encoded_clips(
        self, cutoff_iso: str, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        return self._read_conn.execute(
            """SELECT id, encoded_path, stem, recorded_at,
                      protect_from_retention, status
               FROM clips
               WHERE recorded_at < ?
                 AND encoded_path IS NOT NULL
                 AND encoded_path != ''
                 AND deleted_at IS NULL
               ORDER BY recorded_at ASC
               LIMIT ? OFFSET ?""",
            (cutoff_iso, limit, offset),
        ).fetchall()

    def list_uploaded_clips_oldest_first(
        self, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        return self._read_conn.execute(
            """SELECT id, stem, file_size, protect_from_retention,
                      created_at
               FROM clips
               WHERE status = 'UPLOADED'
                 AND deleted_at IS NULL
               ORDER BY created_at ASC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()

    def has_active_task_for_clip(self, clip_id: str) -> bool:
        rows = self._read_conn.execute(
            "SELECT payload FROM tasks WHERE status IN ('PENDING', 'RUNNING')"
        ).fetchall()
        for row in rows:
            payload = json_loads(row["payload"]) or {}
            if payload.get("clip_id") == clip_id:
                return True
        return False

    def batch_soft_delete(self, clip_ids: list[str]) -> int:
        if not clip_ids:
            return 0
        placeholders = ", ".join("?" for _ in clip_ids)
        now = datetime.now(timezone.utc).isoformat()
        with self.tx() as cur:
            cur.execute(
                f"""UPDATE clips
                    SET deleted_at = ?, updated_at = ?, status = ?
                    WHERE id IN ({placeholders})""",  # nosec
                (now, now, ClipStatus.DONE.name) + tuple(clip_ids),
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # URL History
    # ------------------------------------------------------------------

    def insert_url_history(self, clip_id: str, url: str) -> None:
        with self.tx() as cur:
            cur.execute(
                "INSERT INTO url_history (id, clip_id, url) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), clip_id, url),
            )

    def get_url_history(self, clip_id: str) -> list[dict[str, Any]]:
        rows = self._read_conn.execute(
            "SELECT url, copied_at FROM url_history WHERE clip_id = ? ORDER BY copied_at DESC",
            (clip_id,),
        ).fetchall()
        return [{"url": r["url"], "copied_at": r["copied_at"]} for r in rows]
