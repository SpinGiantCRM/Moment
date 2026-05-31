"""Tests for core/gsr_watcher.py — GSR watcher for new MKV files."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.gsr_watcher import GSRWatcher


@pytest.fixture
def watcher(tmp_path: Path) -> GSRWatcher:
    d = tmp_path / "gsr_output"
    d.mkdir()
    return GSRWatcher(output_dir=str(d))


class TestInitialization:
    def test_not_running_initially(self, watcher: GSRWatcher) -> None:
        assert not watcher._running

    def test_output_dir_created_on_start(self, tmp_path: Path) -> None:
        d = tmp_path / "new_dir"
        w = GSRWatcher(output_dir=str(d))
        assert not d.exists()
        w.start()
        assert d.exists()
        w.stop()

    def test_poll_interval_default(self) -> None:
        from moment.core.gsr_watcher import _POLL_INTERVAL
        w = GSRWatcher(output_dir="/tmp")
        assert w._poll_interval == _POLL_INTERVAL


class TestStartStop:
    def test_start_seeds_known_files(self, tmp_path: Path) -> None:
        d = tmp_path / "out"
        d.mkdir()
        (d / "existing.mkv").touch()
        w = GSRWatcher(output_dir=str(d))
        assert len(w._known_files) == 0
        w.start()
        assert len(w._known_files) == 1
        w.stop()

    def test_double_start_noop(self, tmp_path: Path) -> None:
        w = GSRWatcher(output_dir=str(tmp_path))
        w.start()
        assert w._running
        w.start()  # no-op
        w.stop()

    def test_stop_joins_thread(self, tmp_path: Path) -> None:
        w = GSRWatcher(output_dir=str(tmp_path))
        w.start()
        w.stop()
        assert w._thread is None or not w._thread.is_alive()


class TestPollingLoop:
    def test_detects_new_file(self, tmp_path: Path) -> None:
        detected: list[Path] = []
        d = tmp_path / "poll_out"
        d.mkdir()
        w = GSRWatcher(output_dir=str(d), on_new_clip=lambda p: detected.append(p), poll_interval=0.1)
        w.start()
        time.sleep(0.05)
        (d / "new_clip.mkv").touch()
        time.sleep(0.3)
        w.stop()
        assert any("new_clip" in str(p) for p in detected)

    def test_callback_fires_for_new_file(self, tmp_path: Path) -> None:
        detected: list[Path] = []
        d = tmp_path / "cb_out"
        d.mkdir()
        w = GSRWatcher(output_dir=str(d), on_new_clip=lambda p: detected.append(p), poll_interval=0.1)
        w.start()
        time.sleep(0.05)
        (d / "replay.mkv").touch()
        time.sleep(0.3)
        w.stop()
        assert len(detected) >= 1

    def test_non_mkv_files_ignored(self, tmp_path: Path) -> None:
        detected: list[Path] = []
        d = tmp_path / "nonmkv"
        d.mkdir()
        w = GSRWatcher(output_dir=str(d), on_new_clip=lambda p: detected.append(p), poll_interval=0.1)
        w.start()
        time.sleep(0.05)
        (d / "notes.txt").touch()
        time.sleep(0.3)
        w.stop()
        assert len(detected) == 0

    def test_callback_exception_handled(self, tmp_path: Path) -> None:
        def bad_cb(p: Path) -> None:
            raise RuntimeError("boom")

        d = tmp_path / "bad_cb"
        d.mkdir()
        w = GSRWatcher(output_dir=str(d), on_new_clip=bad_cb, poll_interval=0.1)
        w.start()
        time.sleep(0.05)
        (d / "crash_test.mkv").touch()
        time.sleep(0.3)
        w.stop()
        # Should not raise


class TestFileTracking:
    def test_fires_once_per_file(self, tmp_path: Path) -> None:
        detected: list[Path] = []
        d = tmp_path / "once"
        d.mkdir()
        w = GSRWatcher(output_dir=str(d), on_new_clip=lambda p: detected.append(p), poll_interval=0.1)
        w.start()
        time.sleep(0.05)
        f = d / "unique.mkv"
        f.touch()
        time.sleep(0.4)
        w.stop()
        # File should only be detected once
        mkv_detected = [p for p in detected if p.name == "unique.mkv"]
        assert len(mkv_detected) == 1


class TestInotifyFallback:
    def test_poll_fallback_when_inotify_unavailable(self, tmp_path: Path) -> None:
        with patch("moment.core.gsr_watcher._INOTIFY_AVAILABLE", False):
            d = tmp_path / "fallback"
            d.mkdir()
            detected: list[Path] = []
            w = GSRWatcher(output_dir=str(d), on_new_clip=lambda p: detected.append(p), poll_interval=0.1)
            w.start()
            time.sleep(0.05)
            (d / "fallback_test.mkv").touch()
            time.sleep(0.3)
            w.stop()
            assert len(detected) >= 1
