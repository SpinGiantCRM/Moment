"""Tests for moment.ui.editor.timeline_panel — TimelinePanel + _TimelineWidget."""

from __future__ import annotations

from moment.core.models import SegmentEdit
from moment.ui.editor.timeline_panel import TimelinePanel, _fmt, _Segment, _TimelineWidget


class TestTimelineWidgetInit:
    def test_creates_default_single_segment(self, qapp):
        widget = _TimelineWidget(total_duration=60.0)
        assert widget.segment_count() == 1

    def test_zero_duration_clamped(self, qapp):
        widget = _TimelineWidget(total_duration=0.0)
        assert widget._total == 0.1

    def test_properties_initial(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        assert widget.trim_start == 0.0
        assert widget.trim_end == 30.0
        assert widget.split_points == []

    def test_signals_exist(self, qapp):
        widget = _TimelineWidget(total_duration=10.0)
        assert hasattr(widget, "timeline_changed")
        assert hasattr(widget, "seek_requested")


class TestTimelineWidgetSegmentOps:
    def test_segments_property(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        segs = widget.segments
        assert len(segs) == 1
        assert isinstance(segs[0], SegmentEdit)
        assert segs[0].start == 0.0
        assert segs[0].end == 30.0
        assert segs[0].speed == 1.0

    def test_split_at_playhead(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.split_at_playhead(15.0)
        assert widget.segment_count() == 2
        assert len(widget.split_points) == 1
        assert widget.split_points[0] == 15.0

    def test_split_at_playhead_noop_on_boundary(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.split_at_playhead(0.0)
        assert widget.segment_count() == 1

        widget.split_at_playhead(30.0)
        assert widget.segment_count() == 1

    def test_set_speed(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.split_at_playhead(15.0)
        widget.set_speed(0, 2.0)
        assert widget._segments[0].speed == 2.0
        widget.set_speed(1, 0.5)
        assert widget._segments[1].speed == 0.5

    def test_set_speed_out_of_range(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.set_speed(99, 9.0)  # no-op
        assert widget._segments[0].speed == 1.0

    def test_selected_segment_none_initially(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        assert widget.selected_segment() is None

    def test_set_bookmarks(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.set_bookmarks([5.0, 10.0, 20.0])
        assert widget._bookmarks == [5.0, 10.0, 20.0]

    def test_set_profile(self, qapp):
        widget = _TimelineWidget(total_duration=60.0)
        segs = [
            SegmentEdit(start=0.0, end=30.0, speed=1.0),
            SegmentEdit(start=30.0, end=60.0, speed=2.0),
        ]
        widget.set_profile(
            trim_start=5.0,
            trim_end=55.0,
            split_points=[30.0],
            segments=segs,
        )
        assert widget.trim_start == 5.0
        assert widget.trim_end == 55.0
        assert widget.split_points == [30.0]
        assert widget.segment_count() == 2

    def test_set_profile_none_trim(self, qapp):
        widget = _TimelineWidget(total_duration=60.0)
        widget.set_profile(None, None, [], [])
        assert widget.trim_start == 0.0
        assert widget.trim_end == 60.0


class TestTimelineWidgetRebuildSegments:
    def test_rebuild_from_split_points(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget._trim_start = 0.0
        widget._trim_end = 30.0
        widget._split_points = [10.0, 20.0]
        widget._rebuild_segments()
        assert widget.segment_count() == 3
        assert widget._segments[0].start == 0.0
        assert widget._segments[0].end == 10.0
        assert widget._segments[1].start == 10.0
        assert widget._segments[1].end == 20.0
        assert widget._segments[2].start == 20.0
        assert widget._segments[2].end == 30.0

    def test_rebuild_dedup_boundaries(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget._trim_start = 0.0
        widget._trim_end = 30.0
        widget._split_points = [10.0, 10.0, 20.0]
        widget._rebuild_segments()
        assert widget.segment_count() == 3


class TestTimelineWidgetPaint:
    def test_paint_does_not_crash(self, qapp):
        widget = _TimelineWidget(total_duration=30.0)
        widget.resize(400, 100)
        widget.split_at_playhead(15.0)
        widget.set_bookmarks([5.0, 10.0])
        widget.repaint()  # triggers paintEvent


class TestTimelinePanelInit:
    def test_create(self, qapp):
        panel = TimelinePanel(total_duration=30.0)
        assert panel.trim_start == 0.0
        assert panel.trim_end == 30.0
        assert panel.split_points == []

    def test_signals_exist(self, qapp):
        panel = TimelinePanel(total_duration=10.0)
        assert hasattr(panel, "profile_changed")

    def test_set_bookmarks(self, qapp):
        panel = TimelinePanel(total_duration=30.0)
        panel.set_bookmarks([5.0, 10.0])
        assert panel._timeline._bookmarks == [5.0, 10.0]

    def test_set_profile(self, qapp):
        panel = TimelinePanel(total_duration=60.0)
        panel.set_profile(10.0, 50.0, [30.0], [])
        assert panel.trim_start == 10.0
        assert panel.trim_end == 50.0
        assert panel.split_points == [30.0]


class TestTimelinePanelSpeed:
    def test_speed_combo_updates_segment(self, qapp):
        panel = TimelinePanel(total_duration=30.0)
        panel._timeline.split_at_playhead(15.0)
        panel._timeline._selected_segment = 0
        panel._speed_combo.setCurrentText("2")
        assert panel._timeline._segments[0].speed == 2.0

    def test_speed_combo_no_selection_uses_last(self, qapp):
        panel = TimelinePanel(total_duration=30.0)
        panel._timeline.split_at_playhead(15.0)
        panel._timeline._selected_segment = None
        panel._speed_combo.setCurrentText("4")
        # Last segment (index 1) should get speed 4
        assert panel._timeline._segments[1].speed == 4.0

    def test_speed_combo_invalid_value(self, qapp):
        panel = TimelinePanel(total_duration=30.0)
        panel._timeline.split_at_playhead(15.0)
        original_speed = panel._timeline._segments[0].speed
        # Call _on_speed_changed directly with invalid input to test ValueError path
        panel._on_speed_changed("not-a-number")
        # Speed should remain unchanged after invalid input
        assert panel._timeline._segments[0].speed == original_speed


class TestFmt:
    def test_fmt_seconds(self):
        assert _fmt(0) == "0:00"
        assert _fmt(30) == "0:30"
        assert _fmt(65) == "1:05"
        assert _fmt(3661) == "61:01"

    def test_fmt_negative_clamped(self):
        assert _fmt(-5) == "0:00"


class TestSegmentDataclass:
    def test_segment_defaults(self):
        s = _Segment(start=0.0, end=10.0)
        assert s.start == 0.0
        assert s.end == 10.0
        assert s.speed == 1.0
        assert s.color == ""
