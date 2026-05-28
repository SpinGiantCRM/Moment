"""Retention manager — age-based and disk-space retention policies.

- Source files (MKV): delete >90 days old
- Encoded files (MP4): delete >3 years old
- Cloud (R2): 8 GB rolling FIFO limit

Runs on startup and every 24 hours.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from clip_tray.core.models import Clip, ClipStatus
from clip_tray.core.store import Store
from clip_tray.utils.system import human_size

logger = logging.getLogger(__name__)

# Retention thresholds
SOURCE_MAX_AGE_DAYS = 90
ENCODED_MAX_AGE_DAYS = 3 * 365  # ~3 years
CLOUD_SIZE_LIMIT_BYTES = 8 * 1024 * 1024 * 1024  # 8 GB
RETENTION_INTERVAL = 24 * 3600  # 24 hours


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
    ) -> None:
        """Args:
            store: The application store.
            source_max_age_days: Delete source MKVs older than this.
            encoded_max_age_days: Delete encoded MP4s older than this.
            cloud_size_limit_bytes: Cloud storage limit (FIFO eviction).
            on_purged: Called as ``on_purged(count, freed_bytes)`` after purge.
        """
        self._store = store
        self._source_max_age = source_max_age_days
        self._encoded_max_age = encoded_max_age_days
        self._cloud_limit = cloud_size_limit_bytes
        self._on_purged = on_purged
        self._timer: threading.Timer | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin periodic retention enforcement."""
        if self._running:
            return
        self._running = True
        # Run immediately on startup
        self.enforce()
        self._schedule()

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

    def _on_tick(self) -> None:
        try:
            self.enforce()
        except Exception:
            logger.exception("Error during retention enforcement")
        finally:
            self._schedule()

    def _enforce_source_age(self) -> tuple[int, int]:
        """Delete source MKV files older than the threshold."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._source_max_age)
        purged = 0
        freed = 0

        clips = self._store.list_clips(
            limit=10_000,
            sort_by="created_at",
            include_deleted=False,
        )

        for clip in clips:
            if clip.protect_from_retention:
                continue
            if clip.recorded_at >= cutoff:
                continue
            # Check if the file still exists
            if clip.source_path.is_file():
                try:
                    size = clip.source_path.stat().st_size
                    clip.source_path.unlink()
                    freed += size
                    purged += 1
                    logger.debug("Retention: deleted source %s (%s old)", clip.stem, _age_str(clip.recorded_at))
                except OSError:
                    pass

        return purged, freed

    def _enforce_encoded_age(self) -> tuple[int, int]:
        """Delete encoded MP4 files older than the threshold."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._encoded_max_age)
        purged = 0
        freed = 0

        clips = self._store.list_clips(
            limit=10_000,
            sort_by="created_at",
            include_deleted=False,
        )

        for clip in clips:
            if clip.protect_from_retention:
                continue
            if clip.encoded_path is None:
                continue
            if clip.recorded_at >= cutoff:
                continue
            if clip.encoded_path.is_file():
                try:
                    size = clip.encoded_path.stat().st_size
                    clip.encoded_path.unlink()
                    freed += size
                    purged += 1
                    logger.debug("Retention: deleted encoded %s (%s old)", clip.stem, _age_str(clip.recorded_at))
                except OSError:
                    pass

        return purged, freed

    def _enforce_cloud_limit(self) -> tuple[int, int]:
        """FIFO eviction from cloud storage when total exceeds the limit."""
        # Get uploaded clips ordered oldest-first
        clips = self._store.list_clips(
            status=ClipStatus.UPLOADED,
            limit=10_000,
            sort_by="created_at",
        )

        # Calculate total cloud size from file_size field
        total_size = sum(c.file_size for c in clips if c.file_size > 0)
        if total_size <= self._cloud_limit:
            return 0, 0

        purged = 0
        freed = 0
        for clip in clips:
            if total_size <= self._cloud_limit:
                break
            if clip.protect_from_retention:
                continue
            # Soft-delete the clip (cloud removal will be handled by uploader)
            self._store.delete_clip(clip.id, soft=True)
            total_size -= clip.file_size
            freed += clip.file_size
            purged += 1
            logger.debug("Retention: cloud-FIFO purged %s (%s)", clip.stem, human_size(clip.file_size))

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
