"""Tag repository — tag CRUD and clip–tag associations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from moment.core.models import Tag
from moment.core.repositories.base import BaseRepository, parse_datetime, parse_tags


class TagRepository(BaseRepository):
    """Persistence for tags and clip–tag links."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def get_all(self, limit: int = 100, offset: int = 0) -> list[Tag]:
        rows = self._read_conn.execute(
            "SELECT * FROM tags ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [
            Tag(
                id=r["id"],
                name=r["name"],
                color=r["color"],
                created_at=parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def get_for_clip(self, clip_id: str) -> list[str]:
        rows = self._read_conn.execute(
            """SELECT t.name FROM tags t
               JOIN clip_tags ct ON t.id = ct.tag_id
               WHERE ct.clip_id = ?""",
            (clip_id,),
        ).fetchall()
        return parse_tags(rows)

    def sync_for_clip(self, clip_id: str, tag_names: list[str]) -> None:
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

    def delete(self, tag_id: str) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM clip_tags WHERE tag_id = ?", (tag_id,))
            cur.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
