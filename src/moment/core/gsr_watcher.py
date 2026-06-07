"""GSR watcher — detects new buffer-dump files from gpu-screen-recorder.

Uses inotify (via pyinotify) for low-latency detection. Falls back to
polling every 2 seconds when inotify is unavailable.

Only fires for replay container files (``.mkv`` / ``.mp4``) created *after*
watching starts.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0  # seconds
_SUPPORTED_EXTENSIONS = frozenset({".mkv", ".mp4"})


def _extensions_for_container(container: str | None) -> frozenset[str]:
    """Return file extensions to watch for a GSR container setting."""
    if container:
        ext = f".{container.lstrip('.').lower()}"
        if ext in _SUPPORTED_EXTENSIONS:
            return frozenset({ext})
    return _SUPPORTED_EXTENSIONS


class GSRWatcher:
    """Watches a directory for new replay files created by GSR.

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
        container: str | None = None,
    ) -> None:
        """Args:
        output_dir: Directory where GSR writes buffer-dump files.
        on_new_clip: Called as ``callback(path)`` when a new replay file
            is detected. Runs on a background thread.
        poll_interval: Seconds between polls in polling mode.
        container: GSR container setting (``mkv`` or ``mp4``). When set,
            only that extension is watched; otherwise both are watched.
        """
        self._dir = Path(output_dir).expanduser().resolve()
        self._on_new_clip = on_new_clip
        self._poll_interval = poll_interval
        self._extensions = _extensions_for_container(container)

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
            self._known_files = self._list_replay_files()

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="gsr-watcher",
        )
        self._thread.start()

        try:
            import inotify.adapters as _ia  # type: ignore[import-untyped]  # noqa: F401

            backend = "inotify"
        except ImportError:
            backend = "poll"

        logger.info(
            "GSR watcher started (%s) on %s [%s]",
            backend,
            self._dir,
            ", ".join(sorted(self._extensions)),
        )

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

    def _list_replay_files(self) -> set[Path]:
        """Return all replay files currently in the watch directory."""
        files: set[Path] = set()
        for ext in self._extensions:
            files.update(self._dir.glob(f"*{ext}"))
        return files

    def _is_replay_file(self, path: Path) -> bool:
        """Return ``True`` if *path* is a replay file we should track."""
        return path.suffix.lower() in self._extensions and path.is_file()

    def _watch_loop(self) -> None:
        """Main watch loop — uses inotify if available, else polls."""
        try:
            import importlib.util

            if importlib.util.find_spec("inotify.adapters") is not None:
                self._watch_inotify()
            else:
                self._watch_poll()
        except Exception:
            self._watch_poll()

    def _watch_inotify(self) -> None:
        """inotify-based watch loop."""
        import inotify.adapters as _ia  # type: ignore[import-untyped]

        try:
            adapter = _ia.Inotify()

            # Monitor for IN_CLOSE_WRITE (file completely written)
            mask = _ia.IN_CLOSE_WRITE | _ia.IN_MOVED_TO | _ia.IN_CREATE
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

                if self._is_replay_file(filepath):
                    self._handle_new_file(filepath)

        except Exception:
            if self._running:
                logger.exception("inotify error; falling back to polling")
                self._watch_poll()

    def _watch_poll(self) -> None:
        """Polling-based watch loop (fallback)."""
        while self._running:
            try:
                current_files = self._list_replay_files()
                with self._lock:
                    new_files = current_files - self._known_files
                    self._known_files = current_files

                for fp in sorted(new_files, key=lambda p: p.stat().st_mtime):
                    self._handle_new_file(fp)

            except (OSError, FileNotFoundError) as exc:
                # Directory may have been deleted
                logger.debug("GSR watch dir error: %s", exc)
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
