"""Tests for core/gsr_watcher.py — GSR file watcher.

Mocks inotify and filesystem operations. Never creates real watchers.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.gsr_watcher import GSRWatcher


@pytest.fixture
def tmp_watch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "gsr_output"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_expands_user_path(self) -> None:
        w = GSRWatcher(output_dir="~/Videos/Moment")
        assert "~" not in str(w._dir)

    def test_creates_dir_on_start(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "new_dir"
        w = GSRWatcher(output_dir=new_dir)
        w.start()
        assert new_dir.is_dir()
        w.stop()

    def test_on_new_clip_callback(self, tmp_watch_dir: Path) -> None:
        called: list[Path] = []
        w = GSRWatcher(output_dir=tmp_watch_dir, on_new_clip=lambda p: called.append(p))
        assert w._on_new_clip is not None
        w.stop()


# ---------------------------------------------------------------------------
# Polling fallback
# ---------------------------------------------------------------------------


class TestPolling:
    def test_poll_detects_new_file(self, tmp_watch_dir: Path) -> None:
        """Polling mode detects a newly created .mkv file."""
        called: list[Path] = []
        w = GSRWatcher(
            output_dir=tmp_watch_dir,
            on_new_clip=lambda p: called.append(p),
            poll_interval=0.1,
        )

        with patch.object(w, "_watch_inotify"):
            # Force polling mode
            w._watch_loop = w._watch_poll
            w.start()

            # Create a new file
            new_file = tmp_watch_dir / "replay_001.mkv"
            new_file.write_bytes(b"dummy video")

            # Give the poll loop time to detect it
            time.sleep(0.3)
            w.stop()

        assert len(called) >= 1
        assert any(p.name == "replay_001.mkv" for p in called)

    def test_poll_only_detects_new_files(self, tmp_watch_dir: Path) -> None:
        """Pre-existing files are not re-reported."""
        existing = tmp_watch_dir / "existing.mkv"
        existing.write_bytes(b"old data")
        time.sleep(0.05)

        called: list[Path] = []
        w = GSRWatcher(
            output_dir=tmp_watch_dir,
            on_new_clip=lambda p: called.append(p),
            poll_interval=0.1,
        )

        w._watch_loop = w._watch_poll
        w.start()

        new_file = tmp_watch_dir / "new_one.mkv"
        new_file.write_bytes(b"new data")
        time.sleep(0.3)
        w.stop()

        # existing.mkv should not be reported
        assert not any(p.name == "existing.mkv" for p in called)
        assert any(p.name == "new_one.mkv" for p in called)

    def test_poll_ignores_non_mkv(self, tmp_watch_dir: Path) -> None:
        """Only .mkv files trigger the callback."""
        called: list[Path] = []
        w = GSRWatcher(
            output_dir=tmp_watch_dir,
            on_new_clip=lambda p: called.append(p),
            poll_interval=0.1,
        )

        w._watch_loop = w._watch_poll
        w.start()

        (tmp_watch_dir / "not_a_video.txt").write_bytes(b"text")
        time.sleep(0.3)
        w.stop()

        assert len(called) == 0

    def test_poll_stop_clean(self, tmp_watch_dir: Path) -> None:
        """Ensure stop() terminates the polling loop."""
        w = GSRWatcher(output_dir=tmp_watch_dir, poll_interval=0.1)
        w._watch_loop = lambda: w._watch_poll()
        w.start()
        assert w._running
        w.stop()
        assert not w._running


# ---------------------------------------------------------------------------
# Inotify (mocked)
# ---------------------------------------------------------------------------


class TestInotify:
    def test_inotify_detects_file(self, tmp_watch_dir: Path) -> None:
        """Mock inotify adapter to test event handling."""
        called: list[Path] = []

        new_file = tmp_watch_dir / "test.mkv"

        # Create a mock event generator
        def mock_event_gen(yield_nones=False, timeout_s=2.0):
            if new_file.exists():
                yield (
                    "IN_CLOSE_WRITE",
                    None,
                    str(new_file),
                    None,
                )
            while False:
                yield

        with (
            patch("moment.core.gsr_watcher._INOTIFY_AVAILABLE", True),
            patch("moment.core.gsr_watcher._ia", create=True) as mock_ia,
            patch.object(Path, "is_file", return_value=True),
        ):
            mock_adapter = MagicMock()
            mock_adapter.event_gen.return_value = mock_event_gen()
            mock_ia.Inotify.return_value = mock_adapter

            new_file.write_bytes(b"data")

            w = GSRWatcher(
                output_dir=tmp_watch_dir,
                on_new_clip=lambda p: called.append(p),
            )
            w._running = True
            w._watch_inotify()

            assert len(called) >= 1

    def test_inotify_fallback_to_poll(self, tmp_watch_dir: Path) -> None:
        """If inotify raises, fall back to polling."""
        poll_called: list[str] = []

        def mock_poll():
            poll_called.append("poll")

        with (
            patch("moment.core.gsr_watcher._INOTIFY_AVAILABLE", True),
            patch("moment.core.gsr_watcher._ia", create=True) as mock_ia,
        ):
            mock_ia.Inotify.side_effect = Exception("inotify error")
            w = GSRWatcher(output_dir=tmp_watch_dir)
            w._watch_poll = mock_poll
            w._running = True
            w._watch_inotify()

        assert "poll" in poll_called


# ---------------------------------------------------------------------------
# Callback error handling
# ---------------------------------------------------------------------------


class TestCallbackErrors:
    def test_callback_exception_does_not_crash(self, tmp_watch_dir: Path) -> None:
        """If on_new_clip raises, the watcher continues."""
        def bad_callback(_path: Path) -> None:
            raise RuntimeError("callback error")

        w = GSRWatcher(
            output_dir=tmp_watch_dir,
            on_new_clip=bad_callback,
            poll_interval=0.1,
        )
        w._watch_loop = w._watch_poll
        w.start()

        (tmp_watch_dir / "test.mkv").write_bytes(b"data")
        time.sleep(0.3)
        w.stop()
        # Should not have crashed


# ---------------------------------------------------------------------------
# Double start / stop
# ---------------------------------------------------------------------------


class TestDoubleStartStop:
    def test_double_start_noop(self, tmp_watch_dir: Path) -> None:
        w = GSRWatcher(output_dir=tmp_watch_dir, poll_interval=0.1)
        w._watch_loop = w._watch_poll
        w.start()
        w.start()  # should be no-op
        w.stop()

    def test_double_stop_noop(self, tmp_watch_dir: Path) -> None:
        w = GSRWatcher(output_dir=tmp_watch_dir, poll_interval=0.1)
        w.stop()  # should not raise
        w.stop()
