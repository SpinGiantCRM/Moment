"""Tests for pip_window.py — PiP floating frameless player."""

from __future__ import annotations
import pytest

from pathlib import Path

from moment.ui.widgets.pip_window import _PIP_H, _PIP_W, PipWindow
pytestmark = [pytest.mark.gui]


class TestPipWindowInit:
    """Tests for PipWindow construction and basic properties."""

    def test_create_basic(self, qtbot) -> None:

        """PipWindow can be created with minimal arguments."""
        window = PipWindow(
            clip_id="test-123",
            source_path=Path("/tmp/test.mkv"),
            fps=30.0,
        )
        qtbot.addWidget(window)

        assert window._clip_id == "test-123"
        assert window._source_path == Path("/tmp/test.mkv")
        assert window._fps == 30.0
        assert window.width() == _PIP_W
        assert window.height() == _PIP_H

    def test_create_with_store(self, qtbot) -> None:
        """PipWindow can be created with a store reference."""
        window = PipWindow(
            clip_id="test-456",
            source_path="/tmp/test.mkv",
            fps=24.0,
            store=None,
        )
        qtbot.addWidget(window)
        assert window._clip_id == "test-456"

    def test_fps_capped_at_30(self, qtbot) -> None:
        """FPS values above 30 are capped to 30."""
        window = PipWindow("abc", "/tmp/x.mkv", fps=60.0)
        qtbot.addWidget(window)
        assert window._fps == 30.0

    def test_fps_zero_defaults_to_30(self, qtbot) -> None:
        """FPS of 0 defaults to 30."""
        window = PipWindow("abc", "/tmp/x.mkv", fps=0.0)
        qtbot.addWidget(window)
        assert window._fps == 30.0

    def test_window_flags(self, qtbot) -> None:
        """Window is frameless, stays-on-top, and is a tool window."""
        window = PipWindow("abc", "/tmp/x.mkv")
        qtbot.addWidget(window)

        flags = window.windowFlags()
        from PyQt6.QtCore import Qt
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowStaysOnTopHint
        assert flags & Qt.WindowType.Tool

    def test_delete_on_close(self, qtbot) -> None:
        """Window has WA_DeleteOnClose set."""
        window = PipWindow("abc", "/tmp/x.mkv")
        qtbot.addWidget(window)

        from PyQt6.QtCore import Qt
        assert window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def test_show_without_activating(self, qtbot) -> None:
        """Window has WA_ShowWithoutActivating set."""
        window = PipWindow("abc", "/tmp/x.mkv")
        qtbot.addWidget(window)

        from PyQt6.QtCore import Qt
        assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

class TestPipWindowSignals:
    """Tests for PipWindow signals."""

    def test_clip_clicked_emitted(self, qtbot) -> None:
        """Clicking the image label emits clip_clicked with the clip ID."""
        window = PipWindow("click-me", "/tmp/x.mkv")
        qtbot.addWidget(window)

        with qtbot.waitSignal(window.clip_clicked, timeout=1000) as blocker:
            window._on_clicked(None)

        assert blocker.args == ["click-me"]

    def test_pip_closed_emitted_on_close(self, qtbot) -> None:
        """Closing the window emits pip_closed with the clip ID."""
        window = PipWindow("close-me", "/tmp/x.mkv")
        qtbot.addWidget(window)

        with qtbot.waitSignal(window.pip_closed, timeout=1000) as blocker:
            window.close()

        assert blocker.args == ["close-me"]

    def test_enter_event_pauses_close_timer(self, qtbot) -> None:
        """Mouse enter pauses the auto-close timer."""
        window = PipWindow("abc", "/tmp/x.mkv")
        qtbot.addWidget(window)
        window.show()
        window._close_timer.start()

        window.enterEvent(None)
        assert not window._close_timer.isActive()

    def test_leave_event_restarts_close_timer(self, qtbot) -> None:
        """Mouse leave restarts the auto-close timer."""
        window = PipWindow("abc", "/tmp/x.mkv")
        qtbot.addWidget(window)
        window.show()

        window._close_timer.stop()
        window.leaveEvent(None)
        assert window._close_timer.isActive()

    def test_close_button_closes_window(self, qtbot) -> None:
        """Clicking the × button closes the window and emits pip_closed."""
        from PyQt6.QtCore import Qt as QtCore
        window = PipWindow("abc", "/tmp/x.mkv")
        window.setAttribute(QtCore.WidgetAttribute.WA_DeleteOnClose, False)
        qtbot.addWidget(window)
        window.show()

        with qtbot.waitSignal(window.pip_closed, timeout=1000):
            window._close_btn.click()

    def test_close_event_stops_playback(self, qtbot) -> None:
        """closeEvent emits pip_closed on close."""
        from PyQt6.QtCore import Qt as QtCore
        window = PipWindow("abc", "/tmp/x.mkv")
        window.setAttribute(QtCore.WidgetAttribute.WA_DeleteOnClose, False)
        qtbot.addWidget(window)

        with qtbot.waitSignal(window.pip_closed, timeout=1000):
            window.close()

class TestPipWindowSingleton:
    """Tests for the singleton show_for_clip classmethod."""

    def test_show_for_clip_creates_window(self, qtbot) -> None:
        """show_for_clip creates and shows a PipWindow."""
        from PyQt6.QtCore import Qt as QtCore
        PipWindow._active.clear()

        window = PipWindow.show_for_clip("singleton-1", "/tmp/x.mkv")
        window.setAttribute(QtCore.WidgetAttribute.WA_DeleteOnClose, False)
        qtbot.addWidget(window)

        assert "singleton-1" in PipWindow._active
        assert PipWindow._active["singleton-1"] is window
        assert window.isVisible()

        with qtbot.waitSignal(window.pip_closed, timeout=1000):
            window.close()
        PipWindow._active.clear()

    def test_show_for_clip_replaces_previous(self, qtbot) -> None:
        """Calling show_for_clip for the same clip replaces the old window."""
        from PyQt6.QtCore import Qt as QtCore
        PipWindow._active.clear()

        w1 = PipWindow.show_for_clip("replace-me", "/tmp/x.mkv")
        w1.setAttribute(QtCore.WidgetAttribute.WA_DeleteOnClose, False)
        qtbot.addWidget(w1)
        # Wait for w1's pip_closed from being replaced
        with qtbot.waitSignal(w1.pip_closed, timeout=2000):
            w2 = PipWindow.show_for_clip("replace-me", "/tmp/x.mkv")
        w2.setAttribute(QtCore.WidgetAttribute.WA_DeleteOnClose, False)
        qtbot.addWidget(w2)

        assert PipWindow._active.get("replace-me") is w2
        assert w2.isVisible()

        with qtbot.waitSignal(w2.pip_closed, timeout=1000):
            w2.close()
        PipWindow._active.clear()

class TestPipWindowStop:
    """Tests for playback stop/cleanup."""

    def test_stop_with_no_ffmpeg(self) -> None:
        """stop() is safe when no ffmpeg process is running."""
        window = PipWindow("abc", "/tmp/x.mkv")
        window.stop()  # should not raise

    def test_stop_sets_running_false(self) -> None:
        """stop() sets _running to False."""
        window = PipWindow("abc", "/tmp/x.mkv")
        window._running = True
        window.stop()
        assert not window._running


