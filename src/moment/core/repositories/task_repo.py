"""Task repository — pipeline task queue persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from moment.core.models import Task, TaskKind, TaskStatus
from moment.core.repositories.base import BaseRepository, json_dumps, json_loads, parse_datetime


class TaskRepository(BaseRepository):
    """Persistence for pipeline tasks."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def insert(self, task: Task) -> Task:
        with self.tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO tasks
                   (id, type, priority, payload, status, created_at,
                    retry_count, max_retries, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id, task.type.value, task.priority,
                    json_dumps(task.payload),
                    task.status.name,
                    task.created_at.isoformat(), task.retry_count,
                    task.max_retries, task.error_message,
                ),
            )
        return task

    def get_pending(self, limit: int = 10) -> list[Task]:
        rows = self._read_conn.execute(
            """SELECT * FROM tasks WHERE status = 'PENDING'
               ORDER BY priority DESC, created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            Task(
                id=r["id"],
                type=TaskKind(r["type"]),
                priority=r["priority"],
                payload=json_loads(r["payload"]) or {},
                status=TaskStatus[r["status"]],
                created_at=parse_datetime(r["created_at"]) or datetime.now(timezone.utc),
                retry_count=r["retry_count"],
                max_retries=r["max_retries"],
                error_message=r["error_message"],
            )
            for r in rows
        ]

    def update_status(
        self, task_id: str, status: TaskStatus, error_message: str | None = None
    ) -> None:
        with self.tx() as cur:
            cur.execute(
                """UPDATE tasks SET status = ?, error_message = ?,
                   retry_count = retry_count + 1 WHERE id = ?""",
                (status.name, error_message, task_id),
            )
