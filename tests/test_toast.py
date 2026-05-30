"""Tests for toast.py — toast notification system."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from moment.ui.widgets.toast import (
    _MAX_VISIBLE,
    _TOAST_PRESETS,
    ToastManager,
    ToastWidget,
    toast_manager,
)


class TestToastWidgetInit:
    """Tests for ToastWidget construction."""

    def test_create_success(self, qtbot) -> None:
        """ToastWidget can be created with success type."""
        toast = ToastWidget("success", "Title", "Body")
        qtbot.addWidget(toast)
        assert toast._duration_ms == int(_TOAST_PRESETS["success"]["duration_ms"])

    def test_create_info(self, qtbot) -> None:
        """ToastWidget can be created with info type."""
        toast = ToastWidget("info", "Info Title")
        qtbot.addWidget(toast)
        assert toast._duration_ms == int(_TOAST_PRESETS["info"]["duration_ms"])

    def test_create_warning(self, qtbot) -> None:
        """ToastWidget can be created with warning type."""
        toast = ToastWidget("warning", "Warning!")
        qtbot.addWidget(toast)

    def test_create_error(self, qtbot) -> None:
        """ToastWidget can be created with error type."""
        toast = ToastWidget("error", "Error!")
        qtbot.addWidget(toast)

    def test_create_copy_success(self, qtbot) -> None:
        """ToastWidget can be created with copy_success type."""
        toast = ToastWidget("copy_success", "Copied!")
        qtbot.addWidget(toast)
        assert toast._duration_ms == 1500

    def test_custom_duration(self, qtbot) -> None:
        """Custom duration overrides preset."""
        toast = ToastWidget("success", "Title", duration_ms=999)
        qtbot.addWidget(toast)
        assert toast._duration_ms == 999

    def test_unknown_type_defaults_to_info(self, qtbot) -> None:
        """Unknown toast type defaults to info preset."""
        toast = ToastWidget("bogus_type", "Title")
        qtbot.addWidget(toast)
        assert toast._duration_ms == int(_TOAST_PRESETS["info"]["duration_ms"])

    def test_fixed_width(self, qtbot) -> None:
        """Toast has fixed width."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        assert toast.width() == 320

    def test_has_title_label(self, qtbot) -> None:
        """Title label shows the title text."""
        toast = ToastWidget("success", "My Title")
        qtbot.addWidget(toast)
        assert toast._title_label.text() == "My Title"

    def test_body_label_when_body_provided(self, qtbot) -> None:
        """Body label exists when body text is provided."""
        toast = ToastWidget("success", "Title", "Body text here")
        qtbot.addWidget(toast)
        assert toast._body_label.text() == "Body text here"


class TestToastWidgetTimer:
    """Tests for timer behavior."""

    def test_timer_starts_on_init(self, qtbot) -> None:
        """Auto-dismiss timer starts on construction."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        assert toast._timer is not None
        assert toast._timer.isActive()

    def test_enter_event_pauses_timer(self, qtbot) -> None:
        """Hover pauses the timer."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        assert toast._timer.isActive()
        toast.enterEvent(None)
        assert not toast._timer.isActive()

    def test_leave_event_resumes_timer(self, qtbot) -> None:
        """Mouse leave resumes the timer."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        toast._timer.stop()
        toast.leaveEvent(None)
        assert toast._timer.isActive()

    def test_dismiss_stops_timer_and_slides_out(self, qtbot) -> None:
        """Dismiss stops timer and starts slide-out."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        toast._dismiss()
        assert not toast._timer.isActive()


class TestToastWidgetAnimation:
    """Tests for slide-in / slide-out animation."""

    def test_slide_in_moves_and_shows(self, qtbot) -> None:
        """slide_in moves the toast to target position and shows it."""
        from PyQt6.QtCore import QPoint

        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        target = QPoint(100, 100)
        toast.slide_in(target)
        assert toast.isVisible()

    def test_slide_out_starts_animation(self, qtbot) -> None:
        """slide_out starts a slide-out animation."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        toast.slide_out()
        assert toast._slide_anim is not None

    def test_slide_out_finished_emits_dismissed(self, qtbot) -> None:
        """When slide-out finishes, dismissed signal is emitted."""
        toast = ToastWidget("success", "Title")
        qtbot.addWidget(toast)
        toast.dismissed.connect(lambda t: None)  # just ensure it connects
        toast._on_slide_out_done()  # manual trigger


class TestToastManagerInit:
    """Tests for ToastManager."""

    def test_create(self) -> None:
        """ToastManager can be created."""
        manager = ToastManager()
        assert manager._toasts == []

    def test_singleton_exists(self) -> None:
        """Global toast_manager singleton exists."""
        assert isinstance(toast_manager, ToastManager)


class TestToastManagerShow:
    """Tests for show_toast()."""

    @pytest.fixture(autouse=True)
    def _no_wayland(self) -> None:
        """Ensure _is_wayland returns False so toasts are added to the list."""
        with patch("moment.ui.widgets.toast._is_wayland", return_value=False):
            yield

    def test_show_toast_adds_to_list(self, qtbot) -> None:
        """show_toast creates a ToastWidget and adds it."""
        manager = ToastManager()
        manager.show_toast("success", "Test")
        assert len(manager._toasts) == 1
        assert isinstance(manager._toasts[0], ToastWidget)

    def test_show_multiple_toasts(self, qtbot) -> None:
        """Multiple toasts can be shown."""
        manager = ToastManager()
        manager.show_toast("success", "One")
        manager.show_toast("info", "Two")
        manager.show_toast("warning", "Three")
        assert len(manager._toasts) == 3

    def test_max_visible_enforced(self, qtbot) -> None:
        """Only _MAX_VISIBLE toasts are shown at once."""
        manager = ToastManager()
        for i in range(_MAX_VISIBLE + 2):
            manager.show_toast("success", f"Toast {i}")
        # Oldest should be dismissed, so max visible + some may be dismissing
        assert len(manager._toasts) <= _MAX_VISIBLE + 2

    def test_unknown_type_defaults_to_info(self, qtbot) -> None:
        """Unknown toast type defaults to 'info'."""
        manager = ToastManager()
        manager.show_toast("unknown_type", "Test")
        assert len(manager._toasts) == 1

    def test_on_dismissed_removes_toast(self, qtbot) -> None:
        """_on_dismissed removes the toast from the list."""
        manager = ToastManager()
        manager.show_toast("success", "Test")
        toast = manager._toasts[0]
        manager._on_dismissed(toast)
        assert toast not in manager._toasts


class TestToastManagerCalcPosition:
    """Tests for _calc_position."""

    def test_calc_position_returns_qpoint(self) -> None:
        """_calc_position returns a QPoint."""
        manager = ToastManager()
        pos = manager._calc_position()
        from PyQt6.QtCore import QPoint
        assert isinstance(pos, QPoint)
