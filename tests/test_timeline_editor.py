"""Tests for ui/widgets/timeline_editor.py — dual-handle range selector."""

from __future__ import annotations

from moment.ui.widgets.timeline_editor import TimelineEditor, _fmt


class TestFormatHelper:
    """Tests for the _fmt helper function."""

    def test_zero_seconds(self) -> None:
        assert _fmt(0) == "0:00"

    def test_one_minute(self) -> None:
        assert _fmt(60) == "1:00"

    def test_seconds_and_minutes(self) -> None:
        assert _fmt(90) == "1:30"

    def test_negative_rounds_to_zero(self) -> None:
        assert _fmt(-5) == "0:00"


class TestTimelineEditorInit:
    """Tests for TimelineEditor construction."""

    def test_create_default(self, qapp) -> None:
        editor = TimelineEditor(total_duration=60.0)
        assert editor.trim_start == 0.0
        assert editor.trim_end == 60.0
        assert editor.minimumHeight() > 0

    def test_create_with_range(self, qapp) -> None:
        editor = TimelineEditor(total_duration=120.0, start=10.0, end=80.0)
        assert editor.trim_start == 10.0
        assert editor.trim_end == 80.0

    def test_create_with_explicit_end(self, qapp) -> None:
        editor = TimelineEditor(total_duration=30.0, start=5.0, end=25.0)
        assert editor.trim_start == 5.0
        assert editor.trim_end == 25.0

    def test_minimum_total_duration(self, qapp) -> None:
        editor = TimelineEditor(total_duration=0.0)
        assert editor.trim_start == 0.0
        # end should be at least 0.1

    def test_negative_start_clamped(self, qapp) -> None:
        editor = TimelineEditor(total_duration=60.0, start=-10.0)
        assert editor.trim_start == 0.0


class TestSetRange:
    """Tests for programmatic set_range."""

    def test_set_range_updates_values(self, qapp) -> None:
        editor = TimelineEditor(total_duration=100.0)
        editor.set_range(20.0, 80.0)
        assert editor.trim_start == 20.0
        assert editor.trim_end == 80.0

    def test_set_range_clamps_start(self, qapp) -> None:
        editor = TimelineEditor(total_duration=100.0)
        editor.set_range(-5.0, 90.0)
        assert editor.trim_start == 0.0

    def test_set_range_clamps_end(self, qapp) -> None:
        editor = TimelineEditor(total_duration=100.0)
        editor.set_range(10.0, 150.0)
        assert editor.trim_end == 100.0


class TestSignals:
    """Tests for signal emission."""

    def test_trim_changed_signal_exists(self, qapp) -> None:
        editor = TimelineEditor(total_duration=60.0)
        assert hasattr(editor, "trim_changed")
        calls = []

        def handler(start: float, end: float) -> None:
            calls.append((start, end))
        editor.trim_changed.connect(handler)

        editor.set_range(10.0, 50.0)
        # set_range doesn't emit trim_changed; only drag does.
        # Verify the signal is connectable at least.
        editor.trim_changed.disconnect(handler)
        assert len(calls) == 0


class TestSizeHint:
    """Tests for size hint."""

    def test_size_hint_width(self, qapp) -> None:
        editor = TimelineEditor(total_duration=60.0)
        assert editor.sizeHint().width() >= 300

    def test_size_hint_height(self, qapp) -> None:
        editor = TimelineEditor(total_duration=60.0)
        assert editor.sizeHint().height() >= 40


class TestTimelineEditorEdgeCases:
    """Edge case tests."""

    def test_zero_duration(self, qapp) -> None:
        editor = TimelineEditor(total_duration=0.0)
        assert editor.trim_start >= 0.0

    def test_very_short_duration(self, qapp) -> None:
        editor = TimelineEditor(total_duration=0.01)
        assert editor.trim_start >= 0.0
        assert editor.trim_end > 0.0
