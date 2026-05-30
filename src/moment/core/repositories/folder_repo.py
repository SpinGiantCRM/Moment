"""Folder repository — folder persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from moment.core.models import Folder
from moment.core.repositories.base import BaseRepository, parse_datetime


class FolderRepository(BaseRepository):
    """Persistence for folders."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def save(self, folder: Folder) -> Folder:
        with self.tx() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO folders (id, name, created_at) VALUES (?, ?, ?)",
                (folder.id, folder.name, folder.created_at.isoformat()),
            )
        return folder

    def list_all(self, limit: int = 100, offset: int = 0) -> list[Folder]:
        rows = self._read_conn.execute(
            "SELECT * FROM folders ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [
            Folder(
                id=r["id"],
                name=r["name"],
                created_at=parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
            )
            for r in rows
        ]

    def delete(self, folder_id: str) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
