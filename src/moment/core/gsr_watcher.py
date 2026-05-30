"""GSR watcher — detects new buffer-dump files from gpu-screen-recorder.

Uses inotify (via pyinotify) for low-latency detection. Falls back to
polling every 2 seconds when inotify is unavailable.

Only fires for ``.mkv`` files created *after* watching starts.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0  # seconds

# Try to import inotify; fall back gracefully
try:
    import inotify.adapters as _ia  # type: ignore[import-untyped]
    _INOTIFY_AVAILABLE = True
except ImportError:
    _INOTIFY_AVAILABLE = False
    logger.debug("inotify not available; using polling fallback")


class GSRWatcher:
    """Watches a directory for new ``.mkv`` files created by GSR.

    Thread-safe. Runs a background daemon thread that fires a callback
    when a new replay file appears.

    Typical usage::

        watcher = GSRWatcher(
            output_dir="~/Videos/Moment",
            on_new_clip=lambda path: pipeline.import_clip(path),
        )
        watcher.start()
        # … later …
        watcher.stop()
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        output_dir: str | Path,
        on_new_clip: Callable[[Path], None] | None = None,
        poll_interval: float = _POLL_INTERVAL,
    ) -> None:
        """Args:
            output_dir: Directory where GSR writes buffer-dump files.
            on_new_clip: Called as ``callback(path)`` when a new ``.mkv``
                file is detected. Runs on a background thread.
            poll_interval: Seconds between polls in polling mode.
        """
        self._dir = Path(output_dir).expanduser().resolve()
        self._on_new_clip = on_new_clip
        self._poll_interval = poll_interval

        self._known_files: set[Path] = set()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin watching the output directory.

        Seeds the known-file set so only files created after this call
        will fire the callback.
        """
        if self._running:
            return

        # Ensure the directory exists
        self._dir.mkdir(parents=True, exist_ok=True)

        # Seed known files
        with self._lock:
            self._known_files = set(self._dir.glob("*.mkv"))

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="gsr-watcher",
        )
        self._thread.start()

        if _INOTIFY_AVAILABLE:
            logger.info("GSR watcher started (inotify) on %s", self._dir)
        else:
            logger.info("GSR watcher started (poll) on %s", self._dir)

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        logger.info("GSR watcher stopped")

    # ------------------------------------------------------------------
    # Internal — watch loop
    # ------------------------------------------------------------------

    def _watch_loop(self) -> None:
        """Main watch loop — uses inotify if available, else polls."""
        if _INOTIFY_AVAILABLE:
            self._watch_inotify()
        else:
            self._watch_poll()

    def _watch_inotify(self) -> None:
        """inotify-based watch loop."""
        try:
            adapter = _ia.Inotify()

            # Monitor for IN_CLOSE_WRITE (file completely written)
            mask = (
                _ia.IN_CLOSE_WRITE
                | _ia.IN_MOVED_TO
                | _ia.IN_CREATE
            )
            adapter.add_watch(str(self._dir), mask=mask)

            # Set a timeout so we can check self._running periodically
            # inotify.adapters supports event_gen with timeout
            for event in adapter.event_gen(
                yield_nones=False,
                timeout_s=self._poll_interval,
            ):
                if not self._running:
                    break
                if event is None:
                    continue

                # event is a tuple: (event_type, path_names, target_path, ...)
                _, path_names, target_path, _ = event

                if target_path:
                    filepath = Path(target_path)
                elif path_names:
                    filepath = Path(list(path_names)[0])
                else:
                    continue

                if filepath.suffix == ".mkv" and filepath.is_file():
                    self._handle_new_file(filepath)

        except Exception:
            if self._running:
                logger.exception("inotify error; falling back to polling")
                self._watch_poll()

    def _watch_poll(self) -> None:
        """Polling-based watch loop (fallback)."""
        while self._running:
            try:
                current_files = set(self._dir.glob("*.mkv"))
                with self._lock:
                    new_files = current_files - self._known_files
                    self._known_files = current_files

                for fp in sorted(new_files, key=lambda p: p.stat().st_mtime):
                    self._handle_new_file(fp)

            except (OSError, FileNotFoundError):
                # Directory may have been deleted
                pass
            except Exception:
                logger.exception("Polling error")

            # Sleep, but wake instantly on stop
            self._stop_event.wait(timeout=self._poll_interval)

    def _handle_new_file(self, path: Path) -> None:
        """Fire the callback for a newly detected file."""
        logger.info("New GSR replay detected: %s", path)
        if self._on_new_clip is not None:
            try:
                self._on_new_clip(path)
            except Exception as exc:
                logger.exception("on_new_clip callback error: %s", exc)
