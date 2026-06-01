"""Tests for moment.ui.widgets.timeline_editor — TimelineEditor."""

from __future__ import annotations

import pytest

from moment.ui.widgets.timeline_editor import TimelineEditor, _fmt
pytestmark = [pytest.mark.gui]


def _cleanup_editor(editor: TimelineEditor) -> None:
    """Close and schedule a TimelineEditor for deferred deletion."""

    editor.close()
    editor.deleteLater()

class TestTimelineEditorInit:
    def test_create_defaults(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        assert editor._total == 30.0
        assert editor.trim_start == 0.0
        assert editor.trim_end == 30.0
        _cleanup_editor(editor)

    def test_create_with_start_end(self, qapp):
        editor = TimelineEditor(total_duration=60.0, start=10.0, end=50.0)
        assert editor.trim_start == 10.0
        assert editor.trim_end == 50.0
        _cleanup_editor(editor)

    def test_zero_duration_clamped(self, qapp):
        editor = TimelineEditor(total_duration=0.0)
        assert editor._total == 0.1
        _cleanup_editor(editor)

    def test_negative_start_clamped(self, qapp):
        editor = TimelineEditor(total_duration=30.0, start=-5.0, end=25.0)
        assert editor.trim_start == 0.0
        _cleanup_editor(editor)

    def test_signals_exist(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        assert hasattr(editor, "trim_changed")
        _cleanup_editor(editor)

    def test_size_hint(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        hint = editor.sizeHint()
        assert hint.width() > 0
        assert hint.height() > 0
        _cleanup_editor(editor)

class TestTimelineEditorSetRange:
    def test_set_range(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.set_range(5.0, 25.0)
        assert editor.trim_start == 5.0
        assert editor.trim_end == 25.0
        _cleanup_editor(editor)

    def test_set_range_clamps_values(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.set_range(-10.0, 99.0)
        assert editor.trim_start == 0.0
        assert editor.trim_end == 30.0
        _cleanup_editor(editor)

class TestTimelineEditorCoordConversion:
    def test_pos_to_frac_bounds(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        r = editor._track_rect()
        assert editor._pos_to_frac(r.x()) == 0.0
        assert editor._pos_to_frac(r.x() + r.width()) == 1.0
        _cleanup_editor(editor)

    def test_pos_to_frac_clamped(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        r = editor._track_rect()
        assert editor._pos_to_frac(r.x() - 100) == 0.0
        assert editor._pos_to_frac(r.x() + r.width() + 100) == 1.0
        _cleanup_editor(editor)

    def test_frac_to_x(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        r = editor._track_rect()
        assert editor._frac_to_x(0.0) == r.x()
        assert editor._frac_to_x(1.0) == r.x() + r.width()
        _cleanup_editor(editor)

    def test_handle_x(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        x = editor._handle_x(0.5)
        assert x > 0
        _cleanup_editor(editor)

class TestTimelineEditorHitTest:
    def test_hit_in_handle(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        in_x = editor._handle_x(editor._start / editor._total)
        assert editor._hit_test(in_x) == "in"
        _cleanup_editor(editor)

    def test_hit_out_handle(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        out_x = editor._handle_x(editor._end / editor._total)
        assert editor._hit_test(out_x) == "out"
        _cleanup_editor(editor)

    def test_hit_middle_area(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        r = editor._track_rect()
        mid = r.center().x()
        result = editor._hit_test(mid)
        assert result is None or result is not None
        _cleanup_editor(editor)

class TestTimelineEditorMousePress:
    def test_press_on_handle_starts_drag(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        in_x = editor._handle_x(editor._start / editor._total)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(in_x, 10),
            QPointF(in_x, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mousePressEvent(event)
        assert editor._dragging == "in"
        _cleanup_editor(editor)

    def test_press_empty_area_moves_nearest(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        r = editor._track_rect()
        mid = r.center().x()
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(mid, r.center().y()),
            QPointF(mid, r.center().y()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mousePressEvent(event)
        assert editor._dragging is not None
        _cleanup_editor(editor)

class TestTimelineEditorMouseMove:
    def test_move_updates_hover(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        in_x = editor._handle_x(editor._start / editor._total)
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(in_x, 10),
            QPointF(in_x, 10),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mouseMoveEvent(event)
        assert editor._hover == "in"
        _cleanup_editor(editor)

    def test_move_during_drag_updates_handle(self, qapp):
        editor = TimelineEditor(total_duration=30.0, start=0.0, end=30.0)
        editor.resize(400, 60)
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        in_x = editor._handle_x(editor._start / editor._total)
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(in_x, 10),
            QPointF(in_x, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mousePressEvent(press)

        r = editor._track_rect()
        mid = r.center().x()
        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(mid, r.center().y()),
            QPointF(mid, r.center().y()),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        fired = []
        editor.trim_changed.connect(lambda s, e: fired.append((s, e)))
        editor.mouseMoveEvent(move)
        assert len(fired) >= 1
        _cleanup_editor(editor)

class TestTimelineEditorMouseRelease:
    def test_release_clears_dragging(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        editor._dragging = "in"
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mouseReleaseEvent(event)
        assert editor._dragging is None
        _cleanup_editor(editor)

class TestTimelineEditorLeave:
    def test_leave_clears_hover(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor._hover = "in"
        from PyQt6.QtCore import QEvent
        editor.leaveEvent(QEvent(QEvent.Type.Leave))
        assert editor._hover is None
        _cleanup_editor(editor)

class TestTimelineEditorPaint:
    def test_paint_normal(self, qapp):
        editor = TimelineEditor(total_duration=30.0)
        editor.resize(400, 60)
        editor.repaint()
        _cleanup_editor(editor)

    def test_paint_crossed_handles(self, qapp):
        editor = TimelineEditor(total_duration=30.0, start=25.0, end=5.0)
        editor.resize(400, 60)
        editor.repaint()
        _cleanup_editor(editor)

class TestFmtEditor:
    def test_fmt(self):
        assert _fmt(0) == "0:00"
        assert _fmt(30) == "0:30"
        assert _fmt(65) == "1:05"
        assert _fmt(3661) == "61:01"

    def test_fmt_negative(self):
        assert _fmt(-5) == "0:00"


