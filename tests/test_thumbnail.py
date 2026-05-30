"""Tests for core/thumbnail.py — async thumbnail generation with LRU caching."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.models import Clip
from moment.core.thumbnail import DEFAULT_CACHE_SIZE, Thumbnailer
from moment.utils.ffmpeg import FFmpegError


@pytest.fixture
def thumb_dir(tmp_path: Path) -> str:
    return str(tmp_path / "thumbnails")


@pytest.fixture
def thumbnailer(thumb_dir: str) -> Thumbnailer:
    return Thumbnailer(thumb_dir=thumb_dir, max_cache=5, max_workers=1)


@pytest.fixture
def clip() -> Clip:
    return Clip(
        id=str(uuid.uuid4()),
        stem="test_thumb_clip",
        source_path=Path("/tmp/test_thumb.mkv"),
        duration=30.0,
        file_size=50_000_000,
        video_codec="h264",
        fps=60.0,
        resolution=(1920, 1080),
        title="Test Thumb Clip",
    )


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

class TestCache:
    def test_empty_cache_returns_none(self, clip: Clip, thumbnailer: Thumbnailer) -> None:
        assert thumbnailer.get_cached(clip.stem) is None

    def test_cache_size(self, thumbnailer: Thumbnailer) -> None:
        assert thumbnailer.cache_size == 0

    def test_generate_returns_none_for_new_clip(self, clip: Clip, thumbnailer: Thumbnailer) -> None:
        """generate() returns None because generation happens async."""
        result = thumbnailer.generate(clip)
        assert result is None

    def test_cached_clip_returns_immediately(
        self, clip: Clip, thumbnailer: Thumbnailer, thumb_dir: str
    ) -> None:
        """After a thumbnail is in the cache, generate returns it immediately."""
        thumb_path = Path(thumb_dir) / f"{clip.stem}.jpg"
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(b"fake jpeg data")

        with thumbnailer._lock:
            thumbnailer._cache[clip.stem] = thumb_path

        result = thumbnailer.generate(clip)
        assert result == thumb_path


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_in_flight_deduplication(self, clip: Clip, thumbnailer: Thumbnailer) -> None:
        """Second concurrent generate for same clip should not start new generation."""
        with patch.object(thumbnailer._executor, "submit") as mock_submit:
            # Register as in-flight manually
            with thumbnailer._lock:
                thumbnailer._in_flight.add(clip.stem)

            # Second call should NOT submit to executor
            result = thumbnailer.generate(clip)
            assert result is None
            # executor.submit should not have been called
            mock_submit.assert_not_called()

    def test_callback_queued_during_in_flight(self, clip: Clip, thumbnailer: Thumbnailer) -> None:
        """Callbacks are queued when a generation is already in progress."""
        callback_calls: list[tuple[str, Path | None]] = []

        def cb(stem: str, path: Path | None) -> None:
            callback_calls.append((stem, path))

        with thumbnailer._lock:
            thumbnailer._in_flight.add(clip.stem)

        thumbnailer.generate(clip, callback=cb)
        assert clip.stem in thumbnailer._callbacks


# ---------------------------------------------------------------------------
# Frame extraction (mocked)
# ---------------------------------------------------------------------------

class TestExtractFrame:
    def test_successful_extraction(
        self, clip: Clip, thumbnailer: Thumbnailer, thumb_dir: str
    ) -> None:
        with (
            patch("moment.utils.subprocess.ExternalCommandRunner.run") as mock_run,
            patch("moment.core.thumbnail.find_ffmpeg", return_value="ffmpeg"),
        ):
            mock_run.return_value.returncode = 0

            output = Path(thumb_dir) / f"{clip.stem}.jpg"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fake jpeg")

            thumbnailer._extract_frame(clip.source_path, output, 7.5)

            mock_run.assert_called_once()
            # Should extract at 7.5s (25% of 30s)
            assert "7.5" in mock_run.call_args[0][0]

    def test_extraction_failure(self, clip: Clip, thumbnailer: Thumbnailer, thumb_dir: str) -> None:
        with (
            patch("moment.utils.subprocess.ExternalCommandRunner.run") as mock_run,
            patch("moment.core.thumbnail.find_ffmpeg", return_value="ffmpeg"),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Decoding error"

            output = Path(thumb_dir) / f"{clip.stem}.jpg"

            with pytest.raises(FFmpegError, match="thumbnail failed"):
                thumbnailer._extract_frame(clip.source_path, output, 1.0)

    def test_minimum_snapshot_time(
        self, clip: Clip, thumbnailer: Thumbnailer, thumb_dir: str
    ) -> None:
        """Very short clips should use at least 1 second."""
        clip.duration = 2.0  # 25% = 0.5, minimum is 1.0

        with (
            patch("moment.utils.subprocess.ExternalCommandRunner.run") as mock_run,
            patch("moment.core.thumbnail.find_ffmpeg", return_value="ffmpeg"),
        ):
            mock_run.return_value.returncode = 0
            output = Path(thumb_dir) / f"{clip.stem}.jpg"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fake jpeg")

            with patch.object(thumbnailer, "_extract_frame") as mock_extract:
                thumbnailer._generate_in_thread(clip)
                # Called with time >= 1.0
                call_time = mock_extract.call_args[0][2]
                assert call_time >= 1.0


# ---------------------------------------------------------------------------
# Cache eviction
# ---------------------------------------------------------------------------

class TestCacheEviction:
    def test_eviction_when_exceeding_max(
        self, clip: Clip, thumbnailer: Thumbnailer, thumb_dir: str
    ) -> None:
        """Oldest entry should be evicted when cache exceeds max size."""
        # The cache eviction only happens via _generate_in_thread.
        # Fill the cache to capacity, then call _generate_in_thread to trigger eviction.
        with thumbnailer._lock:
            # Fill cache to exactly capacity (eviction triggers when > max)
            for i in range(thumbnailer._max_cache):
                stem = f"clip_{i}"
                path = Path(thumb_dir) / f"{stem}.jpg"
                thumbnailer._cache[stem] = path

            assert len(thumbnailer._cache) == thumbnailer._max_cache

        # Now call _generate_in_thread which adds one more and evicts oldest
        with (
            patch.object(thumbnailer, "_extract_frame") as mock_extract,
            patch("pathlib.Path.unlink"),
        ):
            mock_extract.side_effect = lambda source, output, time: output.write_bytes(b"x")
            thumbnailer._generate_in_thread(clip)

        # Cache should be at max (evicted oldest "clip_0")
        assert thumbnailer.cache_size == thumbnailer._max_cache
        assert "clip_0" not in thumbnailer._cache
        assert clip.stem in thumbnailer._cache


# ---------------------------------------------------------------------------
# Default thumbnail directory
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_cache_size(self) -> None:
        """Without config, cache size should be DEFAULT_CACHE_SIZE."""
        t = Thumbnailer(config=None)
        assert t._max_cache == DEFAULT_CACHE_SIZE

    def test_explicit_max_cache_overrides(self) -> None:
        """Explicit max_cache argument takes precedence."""
        t = Thumbnailer(config=None, max_cache=100)
        assert t._max_cache == 100


class TestDefaultDir:
    def test_default_thumb_dir_is_expanded(self) -> None:
        """Default thumb_dir (no Config) should resolve to an absolute path."""
        t = Thumbnailer(config=None)
        result = str(t._thumb_dir)
        assert result.startswith("/"), f"Expected absolute path, got: {result!r}"
