"""Settings repository — rate limits and misc settings."""

from __future__ import annotations

import logging
import time

from moment.core.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class SettingsRepository(BaseRepository):
    """Persistence for rate limits and miscellaneous settings."""

    def __init__(self, base: BaseRepository) -> None:
        self._conn = base._conn
        self._read_conn = base._read_conn
        self._lock = base._lock

    def check_rate(self, key: str, interval_secs: float = 60.0) -> str | None:
        """Persistent rate-limit check. Returns error message if rate-limited."""
        now = time.time()
        expire_before = now - (interval_secs * 2)

        with self._lock:
            self.execute_with_retry(
                "DELETE FROM rate_limits WHERE expires_at < ?",
                (expire_before,),
            )
            self._conn.commit()

            row = self.execute_with_retry(
                "SELECT last_called FROM rate_limits WHERE key = ?", (key,)
            ).fetchone()

            if row is not None:
                elapsed = now - row["last_called"]
                if elapsed < interval_secs:
                    wait = int(interval_secs - elapsed + 1)
                    return f"Please wait {wait} seconds before trying again"
                self.execute_with_retry(
                    "UPDATE rate_limits SET last_called = ?, expires_at = ? WHERE key = ?",
                    (now, now + interval_secs, key),
                )
            else:
                self.execute_with_retry(
                    """INSERT OR REPLACE INTO rate_limits
                        (key, last_called, expires_at) VALUES (?, ?, ?)""",
                    (key, now, now + interval_secs),
                )
            self._conn.commit()
            return None
