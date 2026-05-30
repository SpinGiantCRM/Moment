"""Bookmark repository — bookmark persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from moment.core.models import Bookmark
from moment.core.repositories.base import BaseRepository, parse_datetime


class BookmarkRepository(BaseRepository):
    """Persistence for bookmarks."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def insert(self, bm: Bookmark) -> Bookmark:
        with self.tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO bookmarks
                   (id, session_stem, offset_seconds, created_at, label)
                   VALUES (?, ?, ?, ?, ?)""",
                (bm.id, bm.session_stem, bm.offset_seconds, bm.created_at.isoformat(), bm.label),
            )
        return bm

    def get_for_session(self, session_stem: str) -> list[Bookmark]:
        rows = self._read_conn.execute(
            "SELECT * FROM bookmarks WHERE session_stem = ? ORDER BY offset_seconds",
            (session_stem,),
        ).fetchall()
        return [
            Bookmark(
                id=r["id"],
                session_stem=r["session_stem"],
                offset_seconds=r["offset_seconds"],
                created_at=parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
                label=r["label"],
            )
            for r in rows
        ]

    def delete(self, bookmark_id: str) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
