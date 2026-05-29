"""Watcher — monitors MKV directory for new clips via mtime scanning.

Scans every 10 seconds.  Detects files whose mtime is >30 seconds old
and whose size hasn't changed between scans — indicating the file is
no longer being written.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

from moment.utils.system import sanitize_stem

logger = logging.getLogger(__name__)

# Default watch directory
WATCH_DIR = os.path.expanduser("~/Videos")

# Scan interval (seconds)
SCAN_INTERVAL = 10.0

# Minimum file age before considering it "stable" (seconds)
MIN_FILE_AGE = 30.0


class Watcher:
    """Periodic mtime scanner that discovers new MKV files.

    Emits discovered clips via a callback: ``callback(stem, path)``.
    """

    def __init__(
        self,
        watch_dir: str | None = None,
        *,
        on_discovered: Callable[[str, Path], None] | None = None,
        scan_interval: float = SCAN_INTERVAL,
        min_file_age: float = MIN_FILE_AGE,
    ) -> None:
        """Args:
            watch_dir: Directory to watch (default: ``~/Videos``).
            on_discovered: Called when a stable new MKV is found.
            scan_interval: Seconds between scans.
            min_file_age: Seconds a file must be unchanged before discovery.
        """
        self._dir = Path(watch_dir or WATCH_DIR).expanduser().resolve()
        self._on_discovered = on_discovered
        self._scan_interval = scan_interval
        self._min_file_age = min_file_age

        # Track known files: (stem → (mtime, size))
        self._known: dict[str, tuple[float, int]] = {}
        # Track already-emitted stems to prevent re-discovery
        self._discovered: set[str] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin periodic scanning."""
        if self._running:
            return
        self._running = True
        # Do an initial scan immediately (catch errors so timer always schedules)
        try:
            self._scan()
        except Exception:
            logger.exception("Error during initial watcher scan")
        self._schedule()

    def stop(self) -> None:
        """Stop scanning and cancel any pending timer."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def watch_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule(self) -> None:
        """Schedule the next scan if still running."""
        if not self._running:
            return
        self._timer = threading.Timer(self._scan_interval, self._on_tick)
        self._timer.daemon = True
        self._timer.start()

    def _on_tick(self) -> None:
        """Timer callback — scan then re-schedule."""
        try:
            self._scan()
        except Exception:
            logger.exception("Error during watcher scan")
        finally:
            self._schedule()

    def _scan(self) -> None:
        """Scan the watch directory for new / updated MKV files."""
        if not self._dir.is_dir():
            logger.debug("Watch directory does not exist: %s", self._dir)
            return

        import time as _time
        now = _time.time()

        with self._lock:
            current: dict[str, tuple[float, int]] = {}
            try:
                for entry in self._dir.iterdir():
                    if not entry.is_file() or entry.suffix.lower() != ".mkv":
                        continue
                    stat = entry.stat()
                    stem = sanitize_stem(entry.stem)
                    current[stem] = (stat.st_mtime, stat.st_size)
            except OSError as exc:
                logger.warning("Error scanning %s: %s", self._dir, exc)
                return

            now = __import__("time").time()

            for stem, (mtime, size) in current.items():
                age = now - mtime
                prev = self._known.get(stem)

                if prev is None:
                    # New file — just track it for now, emit next scan if stable
                    self._known[stem] = (mtime, size)
                    continue

                prev_mtime, prev_size = prev
                # File is stable: mtime unchanged AND size unchanged AND old enough
                if mtime == prev_mtime and size == prev_size and age >= self._min_file_age:
                    if stem not in self._discovered:
                        self._discovered.add(stem)
                        self._emit_discovery(stem)
                else:
                    # Still growing or changed — update tracking
                    self._known[stem] = (mtime, size)

    def _emit_discovery(self, stem: str) -> None:
        """Notify the callback of a discovered clip."""
        filepath = self._dir / f"{stem}.mkv"
        logger.info("Clip discovered: %s (%s)", stem, filepath)
        if self._on_discovered is not None:
            try:
                self._on_discovered(stem, filepath)
            except Exception as exc:
                logger.exception("Error in discovery callback: %s", exc)
