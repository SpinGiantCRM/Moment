"""Retention manager — age-based and disk-space retention policies.

- Source files (MKV): trash >90 days old
- Encoded files (MP4): trash >3 years old
- Cloud (R2): 8 GB rolling FIFO limit

Files are moved to a trash directory (``~/.local/share/moment/trash/``)
instead of being permanently deleted.  Trash is auto-purged after
``retention_trash_days`` (default: 30).  Set to 0 to skip trash entirely.

ERROR / CORRUPT clips are skipped by default — set
``retention_remove_corrupt=true`` to override.

Runs on startup and every 24 hours.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from moment.core.config import Config
from moment.core.models import Clip, ClipStatus
from moment.core.store import Store
from moment.utils.system import ensure_dir, human_size

logger = logging.getLogger(__name__)

# Retention thresholds
SOURCE_MAX_AGE_DAYS = 90
ENCODED_MAX_AGE_DAYS = 3 * 365  # ~3 years
CLOUD_SIZE_LIMIT_BYTES = 8 * 1024 * 1024 * 1024  # 8 GB
RETENTION_INTERVAL = 24 * 3600  # 24 hours

# ---------------------------------------------------------------------------
# Trash paths
# ---------------------------------------------------------------------------

_DEFAULT_TRASH_DIR = os.path.expanduser("~/.local/share/moment/trash")


class RetentionManager:
    """Enforces age-based and disk-space retention policies.

    Runs on a periodic timer (default: every 24h).  Soft-deletes clips
    that have exceeded their retention limits.
    """

    def __init__(
        self,
        store: Store,
        *,
        source_max_age_days: int = SOURCE_MAX_AGE_DAYS,
        encoded_max_age_days: int = ENCODED_MAX_AGE_DAYS,
        cloud_size_limit_bytes: int = CLOUD_SIZE_LIMIT_BYTES,
        on_purged: Callable[[int, int], None] | None = None,
        config: Config | None = None,
        trash_dir: str | None = None,
    ) -> None:
        """Args:
            store: The application store.
            source_max_age_days: Trash source MKVs older than this.
            encoded_max_age_days: Trash encoded MP4s older than this.
            cloud_size_limit_bytes: Cloud storage limit (FIFO eviction).
            on_purged: Called as ``on_purged(count, freed_bytes)`` after purge.
            config: Optional Config for reading ``retention_trash_days``
                and ``retention_remove_corrupt`` settings.
            trash_dir: Override trash directory (useful for testing).
        """
        self._store = store
        self._source_max_age = source_max_age_days
        self._encoded_max_age = encoded_max_age_days
        self._cloud_limit = cloud_size_limit_bytes
        self._on_purged = on_purged
        self._config = config
        self._trash_dir = trash_dir or _DEFAULT_TRASH_DIR
        self._timer: threading.Timer | None = None
        self._running = False
        self._last_tick: float = 0.0
        self._watchdog_thread: threading.Thread | None = None

        # Cache config values at init time (avoid repeated SQLite reads)
        self._trash_days: int = (
            config.get("retention_trash_days", 30) if config else 30
        )
        self._remove_corrupt: bool = (
            config.get("retention_remove_corrupt", False) if config else False
        )

        # Ensure trash dir exists once (idempotent)
        if self._trash_days > 0:
            ensure_dir(self._trash_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin periodic retention enforcement."""
        if self._running:
            return
        self._running = True
        self._last_tick = time.monotonic()
        # Run immediately on startup
        self.enforce()
        self._schedule()
        self._start_watchdog()

    def stop(self) -> None:
        """Stop periodic enforcement."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def enforce(self) -> tuple[int, int]:
        """Run all retention policies immediately.

        Returns:
            ``(clips_purged, bytes_freed)``
        """
        total_purged = 0
        total_bytes = 0

        purged, freed = self._enforce_source_age()
        total_purged += purged
        total_bytes += freed

        purged, freed = self._enforce_encoded_age()
        total_purged += purged
        total_bytes += freed

        purged, freed = self._enforce_cloud_limit()
        total_purged += purged
        total_bytes += freed

        if total_purged > 0:
            logger.info(
                "Retention purged %d clips, freed %s",
                total_purged,
                human_size(total_bytes),
            )
            if self._on_purged is not None:
                try:
                    self._on_purged(total_purged, total_bytes)
                except Exception as exc:
                    logger.exception("on_purged callback error: %s", exc)

        return total_purged, total_bytes

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(RETENTION_INTERVAL, self._on_tick)
        self._timer.daemon = True
        self._timer.start()

    def _start_watchdog(self) -> None:
        """Start a background thread that detects silent timer death."""
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="retention-watchdog",
        )
        self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """Check every 60s that the timer chain is still alive."""
        while self._running:
            time.sleep(60.0)
            if not self._running:
                break
            elapsed = time.monotonic() - self._last_tick
            if elapsed > 2 * RETENTION_INTERVAL:
                logger.warning(
                    "RetentionManager timer appears stuck — no tick for %.1fs "
                    "(expected interval %.1fs)",
                    elapsed, RETENTION_INTERVAL,
                )

    def _on_tick(self) -> None:
        self._last_tick = time.monotonic()
        try:
            self.enforce()
        except Exception:
            logger.exception("Error during retention enforcement")
        finally:
            self._schedule()

    def _enforce_source_age(self) -> tuple[int, int]:
        """Trash source MKV files older than the threshold."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._source_max_age)
        cutoff_iso = cutoff.isoformat()
        purged = 0
        freed = 0
        offset = 0
        batch_size = 500

        while True:
            rows = self._store.list_old_source_clips(
                cutoff_iso, limit=batch_size, offset=offset
            )
            if not rows:
                break
            offset += batch_size

            for row in rows:
                if row["protect_from_retention"]:
                    continue
                if self._store.has_active_task_for_clip(row["id"]):
                    continue
                if row["status"] in ("ERROR", "CORRUPT") and not self._remove_corrupt:
                    continue
                source_path = Path(row["source_path"])
                if source_path.is_file():
                    try:
                        size = source_path.stat().st_size
                        self._trash_file(source_path, row["stem"])
                        freed += size
                        purged += 1
                        recorded_dt = datetime.fromisoformat(row["recorded_at"])
                        logger.debug(
                            "Retention: trashed source %s (%s old)",
                            row["stem"], _age_str(recorded_dt),
                        )
                    except OSError as exc:
                        logger.debug(
                            "Failed to trash source file %s: %s",
                            row["stem"], exc,
                        )

        return purged, freed

    def _enforce_encoded_age(self) -> tuple[int, int]:
        """Trash encoded MP4 files older than the threshold."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._encoded_max_age)
        cutoff_iso = cutoff.isoformat()
        purged = 0
        freed = 0
        offset = 0
        batch_size = 500

        while True:
            rows = self._store.list_old_encoded_clips(
                cutoff_iso, limit=batch_size, offset=offset
            )
            if not rows:
                break
            offset += batch_size

            for row in rows:
                if row["protect_from_retention"]:
                    continue
                if self._store.has_active_task_for_clip(row["id"]):
                    continue
                if row["status"] in ("ERROR", "CORRUPT") and not self._remove_corrupt:
                    continue
                encoded_path = Path(row["encoded_path"])
                if encoded_path.is_file():
                    try:
                        size = encoded_path.stat().st_size
                        self._trash_file(encoded_path, row["stem"])
                        freed += size
                        purged += 1
                        recorded_dt = datetime.fromisoformat(row["recorded_at"])
                        logger.debug(
                            "Retention: trashed encoded %s (%s old)",
                            row["stem"], _age_str(recorded_dt),
                        )
                    except OSError as exc:
                        logger.debug(
                            "Failed to trash encoded file %s: %s",
                            row["stem"], exc,
                        )

        return purged, freed

    def _skip_error_corrupt(self, clip: Clip) -> bool:
        """Return ``True`` if this clip should be skipped (ERROR/CORRUPT).

        By default, clips with status ``ERROR`` or ``CORRUPT`` are NOT
        retention-purged.  Set config ``retention_remove_corrupt=true``
        to override.
        """
        if clip.status in (ClipStatus.ERROR, ClipStatus.CORRUPT):
            return not self._remove_corrupt
        return False

    def _trash_file(self, path: Path, stem: str) -> None:
        """Move *path* to the trash directory with a timestamp + microsecond suffix.

        When ``retention_trash_days=0``, the file is permanently deleted
        instead of moved to trash.
        """
        if self._trash_days == 0:
            path.unlink()
            logger.debug("Retention: permanently deleted %s (trash_days=0)", path)
            return

        ts = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
        dest = Path(self._trash_dir) / f"{stem}_{ts}{path.suffix}"
        shutil.move(str(path), str(dest))
        logger.debug("Retention: trashed %s → %s", path.name, dest)

    def _enforce_cloud_limit(self) -> tuple[int, int]:
        """FIFO eviction from cloud storage when total exceeds the limit."""
        # Calculate total cloud size from the DB aggregate
        agg = self._store.get_aggregate_stats()
        total_size = agg.get("total_storage_bytes", 0)
        if total_size <= self._cloud_limit:
            return 0, 0

        purged = 0
        freed = 0
        offset = 0
        batch_size = 500
        to_delete: list[str] = []

        while total_size > self._cloud_limit:
            rows = self._store.list_uploaded_clips_oldest_first(
                limit=batch_size, offset=offset
            )
            if not rows:
                break
            offset += batch_size

            for row in rows:
                if total_size <= self._cloud_limit:
                    break
                if row["protect_from_retention"]:
                    continue
                if self._store.has_active_task_for_clip(row["id"]):
                    continue
                to_delete.append(row["id"])
                total_size -= row["file_size"]
                freed += row["file_size"]
                purged += 1
                logger.debug(
                    "Retention: cloud-FIFO purged %s (%s)",
                    row["stem"], human_size(row["file_size"]),
                )

        if to_delete:
            self._store.batch_soft_delete_clips(to_delete)

        return purged, freed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _age_str(dt: datetime) -> str:
    """Human-readable age string, e.g. ``"12d"``."""
    delta = datetime.now(timezone.utc) - dt
    if delta.days > 365:
        return f"{delta.days // 365}y"
    if delta.days > 0:
        return f"{delta.days}d"
    if delta.seconds > 3600:
        return f"{delta.seconds // 3600}h"
    return f"{delta.seconds // 60}m"
