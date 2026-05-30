"""Thumbnailer — async thumbnail generation with LRU caching.

Extracts a single frame from the clip at 25% duration.
Uses a ``ThreadPoolExecutor`` for concurrent generation (max 2 workers).
Emits progress via an optional callback for UI integration.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from moment.core.models import Clip
from moment.utils.ffmpeg import FFmpegError, find_ffmpeg
from moment.utils.subprocess import ExternalCommandRunner
from moment.utils.system import ensure_dir, sanitize_stem

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

_DEFAULT_THUMB_DIR = os.path.expanduser("~/.local/share/moment/thumbnails")
DEFAULT_CACHE_SIZE = 500
DEFAULT_CONCURRENCY = 2
THUMBNAIL_TIMEOUT_S = 30.0


class Thumbnailer:
    """Generates thumbnails asynchronously with a bounded LRU cache.

    Callbacks are signalled on the calling thread — the caller is
    responsible for thread-safe delivery to the UI layer.

    Uses a ``ThreadPoolExecutor(max_workers=2)`` for concurrent ffmpeg
    invocations (2x faster than sequential, won't saturate the GPU).
    """

    def __init__(
        self,
        thumb_dir: str | None = None,
        max_cache: int | None = None,
        config: "Config | None" = None,
        *,
        max_workers: int = DEFAULT_CONCURRENCY,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Args:
            thumb_dir: Directory for thumbnails (overrides Config).
            max_cache: Maximum LRU cache entries. Falls back to
                ``thumbnail_cache_size`` config key, then ``DEFAULT_CACHE_SIZE``.
            config: Optional Config for path overrides and cache size.
            max_workers: ThreadPoolExecutor worker count.
            on_progress: Called as ``on_progress(current, total, clip_id)``
                during batch generation.
        """
        self._config = config
        if thumb_dir is None and config is not None:
            thumb_dir = config.get_path("thumb_dir")
        resolved = thumb_dir or _DEFAULT_THUMB_DIR
        ensure_dir(resolved)
        self._thumb_dir = Path(resolved)

        # Resolve cache size: explicit arg → config key → default
        if max_cache is not None:
            self._max_cache = max_cache
        elif config is not None:
            self._max_cache = config.get("thumbnail_cache_size", DEFAULT_CACHE_SIZE)
        else:
            self._max_cache = DEFAULT_CACHE_SIZE

        self._cache: OrderedDict[str, Path] = OrderedDict()
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        self._callbacks: dict[str, list[Callable[[str, Path | None], None]]] = {}
        self._on_progress = on_progress

        # ThreadPoolExecutor for concurrent ffmpeg generation
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._completed_count = 0
        self._total_count = 0
        self._count_lock = threading.Lock()

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

        # Submit to thread pool for concurrent generation
        self._executor.submit(self._generate_in_thread, clip)
        return None

    def generate_batch(
        self,
        clips: list[Clip],
        *,
        callback: Callable[[str, Path | None], None] | None = None,
    ) -> None:
        """Generate thumbnails for multiple clips concurrently.

        Skips clips that are already cached or in-flight.  Useful for
        pre-fetching thumbnails for upcoming rows during scroll.

        Args:
            clips: The clips to thumbnail.
            callback: Called as ``callback(stem, path_or_none)`` for each
                clip when its thumbnail finishes.
        """
        to_generate: list[Clip] = []
        with self._lock:
            for clip in clips:
                stem = clip.stem
                if stem in self._cache or stem in self._in_flight:
                    continue
                self._in_flight.add(stem)
                if callback is not None:
                    self._callbacks.setdefault(stem, []).append(callback)
                to_generate.append(clip)

        if not to_generate:
            return

        with self._count_lock:
            self._completed_count = 0
            self._total_count = len(to_generate)

        for clip in to_generate:
            self._executor.submit(self._generate_in_thread, clip)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the executor pool.

        Args:
            wait: If ``True``, wait for running futures to complete.
        """
        self._executor.shutdown(wait=wait)

    def __del__(self) -> None:
        """Ensure executor threads don't linger on GC."""
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

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
            self._mark_completed(clip)
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
        self._mark_completed(clip)

    @staticmethod
    def _extract_frame(source: Path, output: Path, time: float) -> None:
        """Extract a single frame at *time* seconds.

        Uses ``ExternalCommandRunner`` with a 30-second timeout to
        prevent hung ffmpeg processes from blocking the pool.
        """
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
        runner = ExternalCommandRunner()
        result = runner.run(cmd, timeout=THUMBNAIL_TIMEOUT_S)
        if result.returncode != 0:
            raise FFmpegError(
                f"thumbnail failed (code={result.returncode}): "
                f"{result.stderr.strip()[-200:]}"
            )
        if not output.is_file() or output.stat().st_size == 0:
            raise FFmpegError(f"thumbnail output missing or empty: {output}")

    def _mark_completed(self, clip: Clip) -> None:
        """Increment completed count and fire progress callback on completion.

        Only emits progress during batch generation (``generate_batch()``).
        Single ``generate()`` calls skip progress since there's no batch context.
        """
        if self._on_progress is None:
            return
        with self._count_lock:
            if self._total_count == 0:
                return  # single generate() — not a batch
            self._completed_count += 1
            current = self._completed_count
            total = self._total_count
        try:
            self._on_progress(current, total, clip.id)
        except Exception:
            pass

    def _dispatch_callbacks(self, stem: str, path: Path | None) -> None:
        """Invoke all registered callbacks for *stem*."""
        with self._lock:
            callbacks = self._callbacks.pop(stem, [])
        for cb in callbacks:
            try:
                cb(stem, path)
            except Exception as exc:
                logger.exception("Thumbnail callback error for %s: %s", stem, exc)
