"""Tests for ui/widgets/overlay.py — QTest rendering, button clicks, auto-hide.

Uses QT_QPA_PLATFORM=offscreen to avoid display dependency.
"""

from __future__ import annotations

import os

import pytest

# Must set offscreen before QApplication is created

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt

from moment.ui.widgets.overlay import (
    _AUTO_HIDE_DEFAULT,
    Overlay,
    _SaveButton,
)

pytestmark = [pytest.mark.gui]


@pytest.fixture
def overlay(qapp) -> Overlay:
    """Return a fresh Overlay instance, properly cleaned up after each test."""
    widget = Overlay(auto_hide_seconds=0)  # disable auto-hide for tests
    yield widget
    widget.hide()
    widget.close()
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_state_is_hidden(self, overlay: Overlay) -> None:
        assert not overlay._showing

    def test_window_flags(self, overlay: Overlay) -> None:
        flags = overlay.windowFlags()
        assert flags & Qt.WindowType.Tool
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowStaysOnTopHint

    def test_fixed_size(self, overlay: Overlay) -> None:
        assert overlay.width() == 440
        assert overlay.height() == 360

    def test_recent_clips_populated(self, qapp) -> None:
        ov = Overlay(recent_clips=[("clip1.mkv", "5s ago"), ("clip2.mkv", "10s ago")])
        assert ov is not None

    def test_default_auto_hide(self, qapp) -> None:
        ov = Overlay()
        assert ov._auto_hide_seconds == _AUTO_HIDE_DEFAULT


# ---------------------------------------------------------------------------
# Show / hide
# ---------------------------------------------------------------------------


class TestShowHide:
    def test_show_overlay(self, overlay: Overlay) -> None:
        overlay.show_overlay()
        assert overlay._showing

    def test_hide_overlay(self, overlay: Overlay) -> None:
        overlay.show_overlay()
        overlay.hide_overlay()
        assert not overlay._showing

    def test_toggle(self, overlay: Overlay) -> None:
        assert not overlay._showing
        overlay.toggle()
        assert overlay._showing
        overlay.toggle()
        assert not overlay._showing

    def test_double_show_resets_timer(self, overlay: Overlay) -> None:
        overlay.show_overlay()
        overlay.show_overlay()  # should not crash or create double state
        assert overlay._showing


# ---------------------------------------------------------------------------
# Save buttons
# ---------------------------------------------------------------------------


class TestSaveButtons:
    def test_save_button_emits_signal(self, overlay: Overlay, qtbot) -> None:
        durations: list[int] = []
        overlay.save_requested.connect(lambda d: durations.append(d))

        overlay.show_overlay()

        btn = overlay._save_buttons[0]  # "Save 30s"
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

        assert 30 in durations

    def test_save_button_confirms(self, overlay: Overlay) -> None:
        overlay.show_overlay()
        overlay.show_save_confirmation(30)

        btn = overlay._save_buttons[0]
        assert btn._state == "saving"


# ---------------------------------------------------------------------------
# SaveButton widget
# ---------------------------------------------------------------------------


class TestSaveButtonWidget:
    def test_idle_state(self, qapp) -> None:
        btn = _SaveButton("Save 30s", 30)
        assert btn._state == "idle"
        assert btn.text() == "Save 30s"

    def test_saving_state(self, qapp) -> None:
        btn = _SaveButton("Save 60s", 60)
        btn.set_state("saving")
        assert btn._state == "saving"
        assert "Saving" in btn.text()

    def test_done_state(self, qapp) -> None:
        btn = _SaveButton("Save 120s", 120)
        btn.set_state("done")
        assert btn._state == "done"
        assert "✓" in btn.text()

    def test_reset(self, qapp) -> None:
        btn = _SaveButton("Save 30s", 30)
        btn.set_state("saving")
        btn.reset()
        assert btn._state == "idle"


# ---------------------------------------------------------------------------
# Recording duration
# ---------------------------------------------------------------------------


class TestRecordingDuration:
    def test_set_duration(self, overlay: Overlay) -> None:
        overlay.set_recording_duration(125)
        assert overlay._duration_seconds == 125
        # 125 seconds = 02:05
        assert "02:05" in overlay._duration_label.text()

    def test_duration_ticker(self, overlay: Overlay) -> None:
        overlay._duration_seconds = 59
        overlay._on_duration_tick()
        assert overlay._duration_seconds == 60
        assert "01:00" in overlay._duration_label.text()


# ---------------------------------------------------------------------------
# Recent clips
# ---------------------------------------------------------------------------


class TestRecentClips:
    def test_set_recent_clips(self, overlay: Overlay) -> None:
        overlay.set_recent_clips([("clip1.mkv", "3s ago"), ("clip2.mkv", "7s ago")])
        # Should not crash

    def test_empty_recent_clips(self, overlay: Overlay) -> None:
        overlay.set_recent_clips([])
        # Should show placeholder without crash

    def test_max_five_clips(self, overlay: Overlay) -> None:
        clips = [(f"clip{i}.mkv", f"{i}s ago") for i in range(10)]
        overlay.set_recent_clips(clips)
        # Should not crash with >5 clips


# ---------------------------------------------------------------------------
# Action links
# ---------------------------------------------------------------------------


class TestActionLinks:
    def test_open_moment_signal(self, overlay: Overlay) -> None:
        fired: list[int] = []
        overlay.open_moment.connect(lambda: fired.append(1))
        overlay.open_moment.emit()
        assert fired == [1]

    def test_open_settings_signal(self, overlay: Overlay) -> None:
        fired: list[int] = []
        overlay.open_settings.connect(lambda: fired.append(1))
        overlay.open_settings.emit()
        assert fired == [1]

    def test_close_overlay_signal(self, overlay: Overlay) -> None:
        fired: list[int] = []
        overlay.close_overlay.connect(lambda: fired.append(1))
        overlay.close_overlay.emit()
        assert fired == [1]


# ---------------------------------------------------------------------------
# Auto-hide
# ---------------------------------------------------------------------------


class TestAutoHide:
    def test_auto_hide_disabled(self, qapp) -> None:
        ov = Overlay(auto_hide_seconds=0)
        assert ov._auto_hide_seconds == 0

    def test_auto_hide_enabled(self, qapp) -> None:
        ov = Overlay(auto_hide_seconds=8)
        assert ov._auto_hide_seconds == 8

    def test_set_auto_hide_seconds(self, overlay: Overlay) -> None:
        overlay.set_auto_hide_seconds(10)
        assert overlay._auto_hide_seconds == 10

    def test_set_below_minimum(self, overlay: Overlay) -> None:
        overlay.set_auto_hide_seconds(2)
        assert overlay._auto_hide_seconds == 4  # clamped to minimum

    def test_set_above_maximum(self, overlay: Overlay) -> None:
        overlay.set_auto_hide_seconds(100)
        assert overlay._auto_hide_seconds == 15  # clamped to maximum
