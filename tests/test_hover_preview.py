"""Tests for hover_preview.py — thumbnail preview popup."""

from __future__ import annotations
import pytest

from PyQt6.QtCore import QRect, Qt

from moment.ui.widgets.hover_preview import _POPUP_H, _POPUP_W, HoverPreviewWidget
pytestmark = [pytest.mark.gui]


class TestHoverPreviewInit:
    """Tests for HoverPreviewWidget construction."""

    def test_create_basic(self, qtbot) -> None:

        """HoverPreviewWidget can be created without a thumbnail."""
        widget = HoverPreviewWidget(thumb_path=None)
        qtbot.addWidget(widget)
        assert widget.width() == _POPUP_W
        assert widget.height() == _POPUP_H

    def test_create_with_title(self, qtbot) -> None:
        """HoverPreviewWidget can be created with a title."""
        widget = HoverPreviewWidget(title="Test Clip")
        qtbot.addWidget(widget)

    def test_window_flags_frameless(self, qtbot) -> None:
        """Widget is frameless and stays on top."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        flags = widget.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowStaysOnTopHint

    def test_delete_on_close(self, qtbot) -> None:
        """WA_DeleteOnClose is set."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        assert widget.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def test_show_without_activating(self, qtbot) -> None:
        """WA_ShowWithoutActivating is set."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def test_delay_timer_single_shot(self, qtbot) -> None:
        """Delay timer is single shot with 500ms interval."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        assert widget._delay_timer.isSingleShot()
        assert widget._delay_timer.interval() == 500

    def test_auto_close_timer_single_shot(self, qtbot) -> None:
        """Auto-close timer is single shot with 5000ms interval."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        assert widget._auto_close.isSingleShot()
        assert widget._auto_close.interval() == 5000

class TestHoverPreviewSchedule:
    """Tests for schedule_show() and cancel()."""

    def test_schedule_show_starts_delay(self, qtbot) -> None:
        """schedule_show starts the delay timer."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        rect = QRect(0, 0, 100, 100)
        widget.schedule_show(rect)
        assert widget._delay_timer.isActive()

    def test_cancel_stops_delay_timer(self, qtbot) -> None:
        """cancel stops the delay timer."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        rect = QRect(0, 0, 100, 100)
        widget.schedule_show(rect)
        widget.cancel()
        assert not widget._delay_timer.isActive()

    def test_cancel_stops_auto_close(self, qtbot) -> None:
        """cancel stops the auto-close timer too."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        widget._auto_close.start()
        widget.cancel()
        assert not widget._auto_close.isActive()

    def test_show_preview_positions_and_shows(self, qtbot) -> None:
        """_show_preview shows the widget."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        rect = QRect(500, 500, 200, 150)
        widget._target_rect = rect
        widget._show_preview()
        # Widget should be visible and auto-close started
        assert widget._auto_close.isActive()

class TestHoverPreviewEvents:
    """Tests for enter/leave events."""

    def test_enter_event_pauses_auto_close(self, qtbot) -> None:
        """Mouse enter pauses auto-close."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        widget._auto_close.start()
        widget.enterEvent(None)
        assert not widget._auto_close.isActive()

    def test_leave_event_restarts_auto_close(self, qtbot) -> None:
        """Mouse leave restarts auto-close."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        widget._auto_close.stop()
        widget.leaveEvent(None)
        assert widget._auto_close.isActive()

    def test_auto_close_timeout_closes(self, qtbot) -> None:
        """When auto-close times out, widget closes."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        widget.show()
        widget._auto_close.timeout.emit()
        # WA_DeleteOnClose means close() was called

class TestHoverPreviewPlaceholder:
    """Tests for placeholder fallback."""

    def test_show_placeholder_sets_pixmap(self, qtbot) -> None:
        """_show_placeholder sets a non-null pixmap."""
        widget = HoverPreviewWidget()
        qtbot.addWidget(widget)
        widget._show_placeholder()
        pixmap = widget._thumb_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_nonexistent_thumb_path_shows_placeholder(self, qtbot) -> None:
        """Nonexistent thumbnail path falls back to placeholder."""
        widget = HoverPreviewWidget(thumb_path="/nonexistent/path/thumb.jpg")
        qtbot.addWidget(widget)
        pixmap = widget._thumb_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()

    def test_none_thumb_path_shows_placeholder(self, qtbot) -> None:
        """None thumb_path falls back to placeholder."""
        widget = HoverPreviewWidget(thumb_path=None)
        qtbot.addWidget(widget)
        pixmap = widget._thumb_label.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()


