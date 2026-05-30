"""Webhook repository — webhook CRUD and delivery logs."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from moment.core.models import Webhook, WebhookLogEntry
from moment.core.repositories.base import BaseRepository, json_dumps, json_loads, parse_datetime

logger = logging.getLogger(__name__)


def redact_webhook_url(url: str) -> str:
    """Return a webhook URL with the token portion replaced by '[REDACTED]'."""
    m = re.match(r"(https://discord\.com/api/webhooks/\d+/)(.*)", url)
    if m:
        return m.group(1) + "[REDACTED]"
    if len(url) > 60:
        return url[:57] + "..."
    return url


class WebhookRepository(BaseRepository):
    """Persistence for webhooks and delivery logs."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def save(self, wh: Webhook) -> Webhook:
        # Store facade handles HTTPS validation + Fernet encryption; repo stores raw
        with self.tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO webhooks
                   (id, url, name, enabled, notify_on, per_game_filter, include_clip_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    wh.id, wh.url, wh.name,
                    int(wh.enabled),
                    json_dumps(wh.notify_on) if wh.notify_on else "[]",
                    json_dumps(wh.per_game_filter) if wh.per_game_filter else None,
                    int(wh.include_clip_url),
                ),
            )
        return wh

    def list_all(self) -> list[Webhook]:
        rows = self._read_conn.execute("SELECT * FROM webhooks").fetchall()
        result: list[Webhook] = []
        for r in rows:
            # Return raw stored values; Store facade handles encryption/decryption
            result.append(Webhook(
                id=r["id"],
                url=r["url"],
                name=r["name"] or "",
                enabled=bool(r["enabled"]),
                notify_on=json_loads(r["notify_on"]) or [],
                per_game_filter=json_loads(r["per_game_filter"]),
                include_clip_url=bool(r["include_clip_url"]),
            ))
        return result

    def get_raw_url(self, webhook_id: str) -> str | None:
        row = self._read_conn.execute(
            "SELECT url FROM webhooks WHERE id = ?", (webhook_id,)
        ).fetchone()
        return row["url"] if row else None

    def delete(self, webhook_id: str) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))

    def insert_log(self, entry: WebhookLogEntry) -> WebhookLogEntry:
        with self.tx() as cur:
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

    def list_logs(
        self,
        *,
        webhook_id: str | None = None,
        success: bool | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[WebhookLogEntry]:
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
        rows = self._read_conn.execute(
            f"SELECT * FROM webhook_log {where_clause} ORDER BY delivered_at DESC LIMIT ? OFFSET ?",  # nosec
            params,
        ).fetchall()
        return [
            WebhookLogEntry(
                id=r["id"],
                webhook_id=r["webhook_id"],
                clip_id=r["clip_id"],
                delivered_at=parse_datetime(r["delivered_at"]) or datetime.now(timezone.utc),
                success=bool(r["success"]),
                status_code=r["status_code"],
                error_message=r["error_message"],
            )
            for r in rows
        ]

    def clear_logs(self) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM webhook_log")

    def get_log_count(self, *, webhook_id: str | None = None) -> int:
        if webhook_id is not None:
            row = self._read_conn.execute(
                "SELECT COUNT(*) as cnt FROM webhook_log WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
        else:
            row = self._read_conn.execute(
                "SELECT COUNT(*) as cnt FROM webhook_log"
            ).fetchone()
        return row["cnt"] if row else 0
