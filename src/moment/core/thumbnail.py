"""Thumbnailer — async thumbnail generation with LRU caching.

Extracts a single frame from the clip at 25% duration.
Runs in its own thread and emits ``thumbnail_ready`` when done.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from moment.core.models import Clip
from moment.utils.ffmpeg import FFmpegError, find_ffmpeg
from moment.utils.subprocess import run_sandboxed
from moment.utils.system import ensure_dir, sanitize_stem

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

_DEFAULT_THUMB_DIR = os.path.expanduser("~/.local/share/moment/thumbnails")
MAX_CACHE_SIZE = 250

_thumb_config: Config | None = None


def _get_config() -> Config | None:
    return _thumb_config


def set_thumb_config(config: Config | None) -> None:
    """Inject a Config instance so thumbnail paths honour user overrides."""
    global _thumb_config
    _thumb_config = config


def get_thumb_dir() -> str:
    """Return the thumbnail directory, respecting Config overrides."""
    cfg = _get_config()
    if cfg is not None:
        return cfg.get_path("thumb_dir")
    return _DEFAULT_THUMB_DIR


class Thumbnailer:
    """Generates thumbnails asynchronously with a bounded LRU cache.

    Callbacks are signalled on the calling thread — the caller is
    responsible for thread-safe delivery to the UI layer.
    """

    def __init__(
        self,
        thumb_dir: str | None = None,
        max_cache: int = MAX_CACHE_SIZE,
    ) -> None:
        resolved = thumb_dir or get_thumb_dir()
        ensure_dir(resolved)
        self._thumb_dir = Path(resolved)
        self._max_cache = max_cache
        self._cache: OrderedDict[str, Path] = OrderedDict()
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._callbacks: dict[str, list[Callable[[str, Path | None], None]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        clip: Clip,
        *,
        callback: Callable[[str, Path | None], None] | None = None,
    ) -> Path | None:
        """Generate (or retrieve cached) thumbnail for *clip*.

        If the thumbnail is already cached the call returns immediately.
        Otherwise the generation runs in a background thread and the
        optional *callback* is invoked on completion.

        Args:
            clip: The clip to thumbnail.
            callback: Called as ``callback(stem, path_or_none)`` when done.

        Returns:
            The cached path if available, otherwise ``None``.
        """
        stem = clip.stem

        # Check cache
        with self._lock:
            if stem in self._cache:
                # Move to end (most-recently-used)
                path = self._cache.pop(stem)
                self._cache[stem] = path
                return path

            # Deduplication: don't generate same thumbnail twice concurrently
            if stem in self._in_flight:
                if callback is not None:
                    self._callbacks.setdefault(stem, []).append(callback)
                return None

            self._in_flight.add(stem)
            if callback is not None:
                self._callbacks.setdefault(stem, []).append(callback)

        t = threading.Thread(
            target=self._generate_in_thread,
            args=(clip,),
            daemon=True,
        )
        t.start()
        return None

    def get_cached(self, stem: str) -> Path | None:
        """Return the cached thumbnail path, or ``None``."""
        with self._lock:
            return self._cache.get(stem)

    @property
    def cache_size(self) -> int:
        """Number of items in the cache."""
        with self._lock:
            return len(self._cache)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_in_thread(self, clip: Clip) -> None:
        """Run thumbnail generation in a background thread."""
        stem = sanitize_stem(clip.stem)
        out = self._thumb_dir / f"{stem}.jpg"

        # Determine timestamp: 25% of duration, minimum 1 second in
        snapshot_time = max(1.0, clip.duration * 0.25)
        try:
            self._extract_frame(clip.source_path, out, snapshot_time)
        except (FFmpegError, FileNotFoundError, OSError) as exc:
            logger.warning("Thumbnail generation failed for %s: %s", stem, exc)
            with self._lock:
                self._in_flight.discard(stem)
            self._dispatch_callbacks(stem, None)
            return

        # Add to cache, evicting oldest if over limit
        with self._lock:
            self._cache[stem] = out
            if len(self._cache) > self._max_cache:
                oldest = next(iter(self._cache))
                old_path = self._cache.pop(oldest)
                try:
                    old_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._in_flight.discard(stem)

        self._dispatch_callbacks(stem, out)

    @staticmethod
    def _extract_frame(source: Path, output: Path, time: float) -> None:
        """Extract a single frame at *time* seconds."""
        find_ffmpeg()
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(time),
            "-i", str(source),
            "-vframes", "1",
            "-q:v", "2",
            "-vf", "scale=320:-1",
            str(output),
        ]
        logger.debug("Thumbnail: %s", cmd)
        result = run_sandboxed(cmd)
        if result.returncode != 0:
            raise FFmpegError(f"thumbnail failed (code={result.returncode}): {result.stderr.strip()[-200:]}")
        if not output.is_file() or output.stat().st_size == 0:
            raise FFmpegError(f"thumbnail output missing or empty: {output}")

    def _dispatch_callbacks(self, stem: str, path: Path | None) -> None:
        """Invoke all registered callbacks for *stem*."""
        with self._lock:
            callbacks = self._callbacks.pop(stem, [])
        for cb in callbacks:
            try:
                cb(stem, path)
            except Exception as exc:
                logger.exception("Thumbnail callback error for %s: %s", stem, exc)
