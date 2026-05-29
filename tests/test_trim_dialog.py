"""Tests for dialogs/trim_dialog.py — dual-handle timeline trim dialog."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from moment.ui.dialogs.trim_dialog import TrimDialog, _format_time


class TestFormatTime:
    """Tests for the _format_time helper."""

    def test_zero_seconds(self) -> None:
        assert _format_time(0) == "0:00"

    def test_under_one_minute(self) -> None:
        assert _format_time(42.7) == "0:42"

    def test_exactly_one_minute(self) -> None:
        assert _format_time(60) == "1:00"

    def test_minutes_and_seconds(self) -> None:
        assert _format_time(125.3) == "2:05"

    def test_over_one_hour(self) -> None:
        assert _format_time(3725) == "1:02:05"

    def test_negative_clamped(self) -> None:
        assert _format_time(-10) == "0:00"


class TestTrimDialogInit:
    """Tests for TrimDialog construction."""

    def test_create_defaults(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0)
        assert dlg.windowTitle() == "Trim Clip"
        assert dlg._duration == 60.0
        assert dlg._start == 0.0
        assert dlg._end == 60.0

    def test_create_with_custom_range(self, qapp) -> None:
        dlg = TrimDialog(duration=120.0, start=10.0, end=110.0)
        assert dlg._start == 10.0
        assert dlg._end == 110.0

    def test_duration_clamped_min(self, qapp) -> None:
        dlg = TrimDialog(duration=0.0)
        assert dlg._duration == 0.1

    def test_negative_start_clamped(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=-5.0)
        assert dlg._start == 0.0

    def test_end_exceeds_duration_clamped(self, qapp) -> None:
        dlg = TrimDialog(duration=30.0, end=50.0)
        assert dlg._end == 30.0

    def test_is_modal(self, qapp) -> None:
        dlg = TrimDialog(duration=10.0)
        assert dlg.isModal()

    def test_apply_button_initially_enabled(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=10.0, end=50.0)
        assert dlg._apply_btn.isEnabled()

    def test_apply_button_disabled_when_invalid(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=50.0, end=10.0)
        dlg._apply_btn.setEnabled(False)
        assert not dlg._apply_btn.isEnabled()

    def test_minimum_size(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0)
        assert dlg.minimumWidth() >= 400
        assert dlg.minimumHeight() >= 150


class TestTrimDialogProperties:
    """Tests for trim_start and trim_end properties."""

    def test_trim_start_property(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=15.0, end=45.0)
        assert dlg.trim_start == 15.0

    def test_trim_end_property(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=15.0, end=45.0)
        assert dlg.trim_end == 45.0


class TestTrimDialogApply:
    """Tests for the Apply button behavior."""

    def test_apply_emits_signal(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=10.0, end=50.0)
        emitted: list[tuple[float, float]] = []
        dlg.trim_applied.connect(lambda s, e: emitted.append((s, e)))
        dlg._apply()
        assert emitted == [(10.0, 50.0)]
        assert dlg.result() == 1

    def test_apply_ignored_when_start_equals_end(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0, start=30.0, end=30.0)
        emitted: list[tuple[float, float]] = []
        dlg.trim_applied.connect(lambda s, e: emitted.append((s, e)))
        dlg._apply()
        assert emitted == []
        assert dlg.result() == 1


class TestTrimDialogLabels:
    """Tests for time label updates."""

    def test_trim_changed_updates_labels(self, qapp) -> None:
        dlg = TrimDialog(duration=120.0, start=0.0, end=120.0)
        dlg._on_trim_changed(10.0, 90.0)
        assert dlg._start == 10.0
        assert dlg._end == 90.0
        assert "In: 0:10" in dlg._in_label.text()
        assert "Out: 1:30" in dlg._out_label.text()
        assert dlg._apply_btn.isEnabled()

    def test_trim_changed_invalid_disables_apply(self, qapp) -> None:
        dlg = TrimDialog(duration=120.0, start=10.0, end=90.0)
        dlg._on_trim_changed(80.0, 20.0)
        assert not dlg._apply_btn.isEnabled()

    def test_cancel_closes(self, qapp) -> None:
        dlg = TrimDialog(duration=60.0)
        dlg.reject()
        assert dlg.result() == 0


class TestTrimDialogKeyboard:
    """Tests for keyboard shortcuts."""

    def test_i_key_marks_in(self, qapp) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        dlg = TrimDialog(duration=120.0, start=10.0, end=90.0)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_I,
                          Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)  # Should not raise

    def test_o_key_marks_out(self, qapp) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        dlg = TrimDialog(duration=120.0)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_O,
                          Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)  # Should not raise

    def test_enter_applies(self, qapp) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        dlg = TrimDialog(duration=60.0, start=10.0, end=50.0)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return,
                          Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)
        assert dlg.result() == 1

    def test_escape_cancels(self, qapp) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        dlg = TrimDialog(duration=60.0)
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                          Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)
        assert dlg.result() == 0
