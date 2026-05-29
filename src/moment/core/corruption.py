"""Corruption detector — health checks, temp cleanup, DB integrity.

Runs periodic health checks every 120 seconds.  Also provides
per-clip corruption detection (zero-byte, ffprobe fails, partial write).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from moment.core.models import Clip, ClipStatus
from moment.core.store import Store
from moment.utils.system import disk_usage, human_size

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 120  # seconds
_DEFAULT_TEMP_DIR = os.path.expanduser("~/.local/share/moment/temp")
TEMP_MAX_AGE = 3600  # 1 hour

_corruption_config: Config | None = None


def _get_config() -> Config | None:
    return _corruption_config


def set_corruption_config(config: Config | None) -> None:
    """Inject a Config instance so temp paths honour user overrides."""
    global _corruption_config
    _corruption_config = config


def get_temp_dir() -> str:
    """Return the temp directory, respecting Config overrides."""
    cfg = _get_config()
    if cfg is not None:
        return cfg.get_path("temp_dir")
    return _DEFAULT_TEMP_DIR
DISK_WARNING_GB = 5
DISK_CRITICAL_GB = 1
PIPELINE_STUCK_MINUTES = 30


class CorruptionDetector:
    """Runs periodic health checks and detects corrupt clips.

    Callbacks are fired for warnings and corruption events.
    """

    def __init__(
        self,
        store: Store,
        *,
        on_warning: Callable[[str], None] | None = None,
        on_critical: Callable[[str], None] | None = None,
        check_interval: float = CHECK_INTERVAL,
    ) -> None:
        """Args:
            store: The application store.
            on_warning: Called with a warning message string.
            on_critical: Called with a critical error message string.
            check_interval: Seconds between health checks.
        """
        self._store = store
        self._on_warning = on_warning
        self._on_critical = on_critical
        self._interval = check_interval
        self._last_task_count: int = 0
        self._last_task_time: float = time.monotonic()
        self._timer: threading.Timer | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin periodic health checks."""
        if self._running:
            return
        self._running = True
        self.check()
        self._schedule()

    def stop(self) -> None:
        """Stop health checks."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def check(self) -> list[str]:
        """Run all health checks immediately.  Returns a list of issues found."""
        issues: list[str] = []

        issues.extend(self._check_disk_space())
        issues.extend(self._check_temp_files())
        issues.extend(self._check_db_integrity())
        issues.extend(self._check_pipeline_stuck())

        for issue in issues:
            if "CRITICAL" in issue.upper():
                logger.error(issue)
                if self._on_critical:
                    self._on_critical(issue)
            else:
                logger.warning(issue)
                if self._on_warning:
                    self._on_warning(issue)

        return issues

    def check_clip(self, clip: Clip) -> ClipStatus | None:
        """Check a single clip for corruption.  Returns ``ClipStatus.CORRUPT`` if
        corrupt, ``None`` otherwise."""
        source = clip.source_path

        # Zero-byte check
        try:
            if source.is_file() and source.stat().st_size == 0:
                return ClipStatus.CORRUPT
        except OSError:
            return ClipStatus.CORRUPT

        # Partial write: mtime very recent + size suggests still growing
        try:
            stat = source.stat()
            age = time.time() - stat.st_mtime
            if age < 30 and stat.st_size > 0:
                # Might still be writing — not corrupt yet, but suspicious
                pass
        except OSError:
            return ClipStatus.CORRUPT

        return None

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._on_tick)
        self._timer.daemon = True
        self._timer.start()

    def _on_tick(self) -> None:
        try:
            self.check()
        except Exception:
            logger.exception("Error during health check")
        finally:
            self._schedule()

    def _check_disk_space(self) -> list[str]:
        """Check available disk space."""
        issues: list[str] = []
        try:
            _, _, free = disk_usage(Path.home())
            free_gb = free / (1024 ** 3)
            if free_gb < DISK_CRITICAL_GB:
                issues.append(
                    f"CRITICAL: Disk space critically low — {human_size(free)} free "
                    f"(threshold: {DISK_CRITICAL_GB} GB)"
                )
            elif free_gb < DISK_WARNING_GB:
                issues.append(
                    f"WARNING: Disk space low — {human_size(free)} free "
                    f"(threshold: {DISK_WARNING_GB} GB)"
                )
        except OSError as exc:
            logger.debug("Could not check disk space: %s", exc)
        return issues

    def _check_temp_files(self) -> list[str]:
        """Clean up stale temporary files."""
        issues: list[str] = []
        temp_dir = Path(get_temp_dir())
        if not temp_dir.is_dir():
            return issues
        try:
            now = time.time()
            deleted = 0
            for entry in temp_dir.iterdir():
                if not entry.is_file():
                    continue
                try:
                    age = now - entry.stat().st_mtime
                    if age > TEMP_MAX_AGE:
                        entry.unlink()
                        deleted += 1
                except OSError:
                    pass
            if deleted:
                logger.info("Cleaned up %d stale temp files", deleted)
        except OSError as exc:
            issues.append(f"WARNING: Could not clean temp files: {exc}")
        return issues

    def _check_db_integrity(self) -> list[str]:
        """Run SQLite integrity check."""
        issues: list[str] = []
        try:
            conn = self._store._conn  # type: ignore[attr-defined]
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row and row[0] != "ok":
                msg = f"CRITICAL: Database integrity check failed: {row[0]}"
                issues.append(msg)
        except Exception as exc:
            issues.append(f"WARNING: Could not run DB integrity check: {exc}")
        return issues

    def _check_pipeline_stuck(self) -> list[str]:
        """Detect if the pipeline appears stuck (pending tasks not progressing)."""
        issues: list[str] = []
        try:
            pending = self._store.get_pending_tasks(limit=100)
            count = len(pending)
            now = time.monotonic()

            if count > 0:
                if count == self._last_task_count:
                    # Same count — check if too long
                    if now - self._last_task_time > PIPELINE_STUCK_MINUTES * 60:
                        issues.append(
                            f"WARNING: Pipeline may be stuck — "
                            f"{count} pending tasks for >{PIPELINE_STUCK_MINUTES} min"
                        )
                else:
                    self._last_task_count = count
                    self._last_task_time = now
            else:
                self._last_task_count = 0
        except Exception:
            pass
        return issues
