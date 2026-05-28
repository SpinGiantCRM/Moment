"""Tests for core/watcher.py — MKV directory mtime scanning."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from clip_tray.core.watcher import MIN_FILE_AGE, SCAN_INTERVAL, WATCH_DIR, Watcher


@pytest.fixture
def watch_dir(tmp_path: Path) -> Path:
    return tmp_path / "Videos"


@pytest.fixture
def watcher(watch_dir: Path) -> Watcher:
    w = Watcher(watch_dir=str(watch_dir), min_file_age=1.0)
    yield w
    w.stop()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_default_watch_dir(self) -> None:
        w = Watcher()
        assert w.watch_dir == Path(WATCH_DIR).expanduser().resolve()

    def test_custom_watch_dir(self, watch_dir: Path) -> None:
        w = Watcher(watch_dir=str(watch_dir))
        assert w.watch_dir == watch_dir.resolve()

    def test_not_running_initially(self, watch_dir: Path) -> None:
        w = Watcher(watch_dir=str(watch_dir))
        assert not w.is_running

    def test_default_scan_interval(self) -> None:
        w = Watcher()
        assert w._scan_interval == SCAN_INTERVAL


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovers_stable_mkv(self, watch_dir: Path) -> None:
        """A .mkv file old enough and stable across two scans should be discovered."""
        discovered: list[tuple[str, Path]] = []

        def on_discovered(stem: str, path: Path) -> None:
            discovered.append((stem, path))

        w = Watcher(watch_dir=str(watch_dir), on_discovered=on_discovered, min_file_age=0.1)

        # Create a .mkv file with an old mtime
        mkv = watch_dir / "test_capture.mkv"
        watch_dir.mkdir(parents=True, exist_ok=True)
        mkv.write_bytes(b"fake mkv data")

        # Make it look old
        old_time = time.time() - 60
        os.utime(str(mkv), (old_time, old_time))

        # First scan: tracks but doesn't emit (needs stability across two scans)
        w._scan()
        # Second scan: file unchanged → emit
        w._scan()
        w.stop()

        assert len(discovered) == 1
        assert discovered[0] == ("test_capture", mkv)

    def test_ignores_non_mkv(self, watch_dir: Path) -> None:
        discovered: list[tuple[str, Path]] = []

        w = Watcher(
            watch_dir=str(watch_dir),
            on_discovered=lambda s, p: discovered.append((s, p)),
            min_file_age=0.1,
        )

        watch_dir.mkdir(parents=True, exist_ok=True)
        txt = watch_dir / "readme.txt"
        txt.write_bytes(b"not a video")

        old_time = time.time() - 60
        os.utime(str(txt), (old_time, old_time))

        w._scan()
        w.stop()

        assert len(discovered) == 0

    def test_ignores_recent_file(self, watch_dir: Path) -> None:
        """A .mkv file whose mtime is too recent should NOT be discovered."""
        discovered: list[tuple[str, Path]] = []

        w = Watcher(
            watch_dir=str(watch_dir),
            on_discovered=lambda s, p: discovered.append((s, p)),
            min_file_age=60.0,  # require 60 seconds old
        )

        watch_dir.mkdir(parents=True, exist_ok=True)
        mkv = watch_dir / "just_captured.mkv"
        mkv.write_bytes(b"just written")

        # mtime is now (very recent)
        w._scan()
        w.stop()

        assert len(discovered) == 0

    def test_does_not_rediscover_known_file(self, watch_dir: Path) -> None:
        discovered: list[tuple[str, Path]] = []

        w = Watcher(
            watch_dir=str(watch_dir),
            on_discovered=lambda s, p: discovered.append((s, p)),
            min_file_age=0.1,
        )

        watch_dir.mkdir(parents=True, exist_ok=True)
        mkv = watch_dir / "stable.mkv"
        mkv.write_bytes(b"stable mkv")

        old_time = time.time() - 60
        os.utime(str(mkv), (old_time, old_time))

        # First scan: track
        w._scan()
        # Second scan: discover
        w._scan()
        assert len(discovered) == 1

        # Third scan should not re-discover
        w._scan()
        assert len(discovered) == 1

        w.stop()

    def test_nonexistent_dir_no_error(self, watch_dir: Path) -> None:
        """Scanning a non-existent directory should not raise."""
        w = Watcher(watch_dir=str(watch_dir / "does_not_exist"))
        # Should not raise
        w._scan()
        w.stop()

    def test_discovered_only_when_stable_across_scans(self, watch_dir: Path) -> None:
        """A file should be discovered when it's stable across two scans."""
        discovered: list[tuple[str, Path]] = []

        w = Watcher(
            watch_dir=str(watch_dir),
            on_discovered=lambda s, p: discovered.append((s, p)),
            min_file_age=0.1,
        )

        watch_dir.mkdir(parents=True, exist_ok=True)
        mkv = watch_dir / "stable_across_scans.mkv"
        mkv.write_bytes(b"first write")

        old_time = time.time() - 60
        os.utime(str(mkv), (old_time, old_time))

        # Scan 1: tracks the file but doesn't emit (needs two scans to confirm stability)
        w._scan()
        assert len(discovered) == 0

        # Scan 2: file is stable (mtime + size unchanged) → emit
        w._scan()
        assert len(discovered) == 1
        assert discovered[0] == ("stable_across_scans", mkv)
        w.stop()


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_starts_timer(self, watch_dir: Path) -> None:
        w = Watcher(watch_dir=str(watch_dir), scan_interval=999.0)
        w.start()
        assert w.is_running
        w.stop()
        assert not w.is_running

    def test_double_start_does_nothing(self, watch_dir: Path) -> None:
        w = Watcher(watch_dir=str(watch_dir), scan_interval=999.0)
        w.start()
        assert w.is_running
        w.start()  # should be a no-op
        assert w.is_running
        w.stop()

    def test_scan_error_does_not_crash(self, watch_dir: Path) -> None:
        """If _scan raises in timer callback, the timer should still reschedule."""
        w = Watcher(watch_dir=str(watch_dir), scan_interval=0.05)
        # Replace _scan with a function that raises — both the initial scan
        # in start() and the timer callbacks should catch the error.
        def _failing_scan() -> None:
            raise RuntimeError("simulated")
        w._scan = _failing_scan  # type: ignore[assignment]
        w.start()
        # Should not crash — start() catches the exception
        import time
        time.sleep(0.2)
        w.stop()
        assert not w.is_running
