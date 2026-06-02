"""Timeline panel — multi-segment clip editor.

A custom QPainter widget showing a horizontal timeline with coloured
segments.  Supports:

- Split at playhead (creates two segments)
- Per-segment speed: 0.25× / 0.5× / 1× / 1.5× / 2× / 3× / 4×
- Drag segment boundary handles to adjust split positions
- Bookmark diamond markers
- Trim handles at start and end of the full clip
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.core.models import SegmentEdit

logger = logging.getLogger(__name__)

# Segment colours (cycling palette)
_SEGMENT_COLORS = [
    "#60a5fa",  # blue
    "#4ade80",  # green
    "#fb923c",  # orange
    "#c084fc",  # purple
    "#f87171",  # red
    "#facc15",  # yellow
    "#2dd4bf",  # teal
    "#f472b6",  # pink
]

_SPEED_OPTIONS = ["0.25", "0.5", "1", "1.5", "2", "3", "4"]
_HANDLE_W = 8
_BAR_H = 32
_MARKER_H = 12


@dataclass
class _Segment:
    """Internal segment descriptor for the timeline."""

    start: float
    end: float
    speed: float = 1.0
    color: str = ""


class _TimelineWidget(QWidget):
    """Custom-painted multi-segment timeline."""

    timeline_changed = pyqtSignal()
    seek_requested = pyqtSignal(float)  # seconds

    def __init__(self, total_duration: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._total = max(total_duration, 0.1)
        self._segments: list[_Segment] = []
        self._split_points: list[float] = []
        self._bookmarks: list[float] = []
        self._trim_start = 0.0
        self._trim_end = total_duration

        self._dragging: str | None = None  # "trim_in", "trim_out", "split_N", or None
        self._drag_offset = 0.0
        self._hover: str | None = None
        self._selected_segment: int | None = None

        self.setMinimumHeight(_BAR_H + 40)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Build default single segment
        if total_duration > 0:
            self._segments.append(_Segment(0.0, total_duration, 1.0, _SEGMENT_COLORS[0]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def segments(self) -> list[SegmentEdit]:
        return [SegmentEdit(start=s.start, end=s.end, speed=s.speed) for s in self._segments]

    @property
    def split_points(self) -> list[float]:
        return list(self._split_points)

    @property
    def trim_start(self) -> float:
        return self._trim_start

    @property
    def trim_end(self) -> float:
        return self._trim_end

    def set_profile(
        self,
        trim_start: float | None,
        trim_end: float | None,
        split_points: list[float],
        segments: list[SegmentEdit],
    ) -> None:
        """Load an existing profile into the timeline."""
        self._trim_start = trim_start or 0.0
        self._trim_end = trim_end or self._total
        self._split_points = list(split_points)

        if segments:
            self._segments = [
                _Segment(
                    start=s.start,
                    end=s.end,
                    speed=s.speed,
                    color=_SEGMENT_COLORS[i % len(_SEGMENT_COLORS)],
                )
                for i, s in enumerate(segments)
            ]
        self.update()

    def set_bookmarks(self, bookmarks: list[float]) -> None:
        """Set bookmark positions on the timeline."""
        self._bookmarks = list(bookmarks)
        self.update()

    def split_at_playhead(self, position: float) -> None:
        """Split the segment containing *position* into two."""
        for i, seg in enumerate(self._segments):
            if seg.start < position < seg.end:
                left = _Segment(
                    start=seg.start,
                    end=position,
                    speed=seg.speed,
                    color=seg.color,
                )
                right = _Segment(
                    start=position,
                    end=seg.end,
                    speed=seg.speed,
                    color=_SEGMENT_COLORS[(len(self._segments) + 1) % len(_SEGMENT_COLORS)],
                )
                self._segments[i : i + 1] = [left, right]
                self._split_points.append(position)
                self._split_points.sort()
                self.timeline_changed.emit()
                self.update()
                return

    def set_speed(self, segment_index: int, speed: float) -> None:
        """Set the playback speed for a given segment."""
        if 0 <= segment_index < len(self._segments):
            self._segments[segment_index].speed = speed
            self.timeline_changed.emit()
            self.update()

    def selected_segment(self) -> int | None:
        """Return the index of the currently selected segment, if any."""
        return self._selected_segment

    def segment_count(self) -> int:
        return len(self._segments)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _track_rect(self) -> QRectF:
        margin = _HANDLE_W
        return QRectF(margin, 20, self.width() - 2 * margin, _BAR_H)

    def _time_to_x(self, time: float) -> float:
        r = self._track_rect()
        frac = time / self._total
        return r.x() + frac * r.width()

    def _x_to_time(self, x: float) -> float:
        r = self._track_rect()
        frac = (x - r.x()) / max(r.width(), 1)
        return max(0.0, min(self._total, frac * self._total))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = self._track_rect()

        # Track background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2a2a2a"))
        p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 4, 4)

        # Draw segments
        for i, seg in enumerate(self._segments):
            x1 = self._time_to_x(seg.start)
            x2 = self._time_to_x(seg.end)
            seg_rect = QRectF(x1, r.y(), x2 - x1, r.height())

            # Segment fill
            seg_color = QColor(seg.color)
            seg_color.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(seg_color)
            p.drawRoundedRect(seg_rect, 3, 3)

            # Speed badge
            if seg.speed != 1.0:
                (x1 + x2) / 2
                font = p.font()
                font.setPointSize(8)
                font.setBold(True)
                p.setFont(font)
                p.setPen(QColor("#fff"))
                p.drawText(
                    QRectF(x1, r.y(), x2 - x1, r.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{seg.speed}x",
                )

        # Split point handles (vertical lines between segments)
        for pt in self._split_points:
            hx = self._time_to_x(pt)
            p.setPen(QPen(QColor("#a1a1aa"), 1, Qt.PenStyle.DashLine))
            p.drawLine(hx, int(r.y()) - _MARKER_H // 2, hx, int(r.bottom()) + _MARKER_H // 2)

        # Bookmarks (diamond markers above the track)
        for bm in self._bookmarks:
            bx = self._time_to_x(bm)
            diamond = QRectF(bx - 3, r.y() - _MARKER_H - 6, 6, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#facc15"))
            p.drawRect(diamond)

        # Trim handles
        trim_colors = {"trim_in": "#60a5fa", "trim_out": "#fb923c"}
        for name, val in [("trim_in", self._trim_start), ("trim_out", self._trim_end)]:
            if val > 0:
                hx = self._time_to_x(val)
            else:
                hx = self._time_to_x(0) if name == "trim_in" else self._time_to_x(self._total)
            p.setPen(Qt.PenStyle.NoPen)
            is_active = self._hover == name or self._dragging == name
            clr = "#f87171" if (name == "trim_in" and val >= self._trim_end) else trim_colors[name]
            p.setBrush(QColor(clr))
            p.drawRoundedRect(
                QRectF(hx - _HANDLE_W // 2, r.y() - 4, _HANDLE_W, r.height() + 8),
                3,
                3,
            )
            if is_active:
                p.setPen(QPen(QColor(clr), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(
                    QRectF(
                        hx - _HANDLE_W // 2 - 2,
                        r.y() - 6,
                        _HANDLE_W + 4,
                        r.height() + 12,
                    ),
                    4,
                    4,
                )

        # Time labels
        p.setPen(QColor("#a1a1aa"))
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)
        for time, label_offset in [(0, 0), (self._total / 2, 40), (self._total, 80)]:
            tx = self._time_to_x(time)
            label = _fmt(time)
            if time == self._total:
                tx -= 30
            p.drawText(QRectF(tx - 20, r.bottom() + 6, 60, 16), Qt.AlignmentFlag.AlignCenter, label)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def _hit_test(self, pos: QPoint) -> tuple[str | None, int]:
        """Return (handle_type, split_index) for the given position."""
        px = pos.x()
        r = self._track_rect()

        # Trim handles (top priority for hit-test)
        for name, val in [("trim_in", self._trim_start), ("trim_out", self._trim_end)]:
            hx = self._time_to_x(val)
            if abs(px - hx) <= _HANDLE_W + 4 and r.y() - 6 <= pos.y() <= r.bottom() + 6:
                return (name, -1)

        # Split point handles
        for i, pt in enumerate(self._split_points):
            hx = self._time_to_x(pt)
            if (
                abs(px - hx) <= _HANDLE_W + 2
                and r.y() - _MARKER_H <= pos.y() <= r.bottom() + _MARKER_H
            ):
                return (f"split_{i}", i)

        return (None, -1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        handle, idx = self._hit_test(event.pos())
        if handle is not None:
            self._dragging = handle
        else:
            # Click on a segment → select it
            time = self._x_to_time(event.pos().x())
            for i, seg in enumerate(self._segments):
                if seg.start <= time <= seg.end:
                    self._selected_segment = i
                    self.seek_requested.emit(time)
                    self.update()
                    return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None:
            time = self._x_to_time(event.pos().x())
            if self._dragging == "trim_in":
                self._trim_start = max(0.0, min(time, self._trim_end - 0.1))
            elif self._dragging == "trim_out":
                self._trim_end = max(self._trim_start + 0.1, min(time, self._total))
            elif self._dragging.startswith("split_"):
                idx = int(self._dragging.split("_")[1])
                clamped = max(0.0, min(self._total, time))
                if 0 <= idx < len(self._split_points):
                    self._split_points[idx] = clamped
                    self._split_points.sort()
                    # Re-track the dragged split point by its old value
                    # Find where the old value is now in the sorted list
                    new_idx = None
                    for j, pt in enumerate(self._split_points):
                        if abs(pt - clamped) < 0.001:
                            new_idx = j
                            break
                    if new_idx is not None:
                        self._dragging = f"split_{new_idx}"
                # Rebuild segments from split points
                self._rebuild_segments()
            self.timeline_changed.emit()
            self.update()
        else:
            handle, _ = self._hit_test(event.pos())
            if handle != self._hover:
                self._hover = handle
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.PointingHandCursor
                )
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = None
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()

    def _rebuild_segments(self) -> None:
        """Rebuild segments from sorted split points + trim boundaries."""
        boundaries = [self._trim_start] + sorted(self._split_points) + [self._trim_end]
        boundaries = sorted(set(boundaries))
        new_segments: list[_Segment] = []
        for i in range(len(boundaries) - 1):
            s, e = boundaries[i], boundaries[i + 1]
            if e - s < 0.01:
                continue
            # Preserve speed from old segment if possible
            speed = 1.0
            for old in self._segments:
                if old.start <= s < old.end:
                    speed = old.speed
                    break
            new_segments.append(_Segment(s, e, speed, _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)]))
        self._segments = new_segments


class TimelinePanel(QWidget):
    """Panel containing the timeline widget + speed controls."""

    profile_changed = pyqtSignal()

    def __init__(self, total_duration: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui(total_duration)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def trim_start(self) -> float:
        return self._timeline.trim_start

    @property
    def trim_end(self) -> float:
        return self._timeline.trim_end

    @property
    def split_points(self) -> list[float]:
        return self._timeline.split_points

    @property
    def segments(self) -> list[SegmentEdit]:
        return self._timeline.segments

    def set_profile(
        self,
        trim_start: float | None,
        trim_end: float | None,
        split_points: list[float],
        segments: list[SegmentEdit],
    ) -> None:
        self._timeline.set_profile(trim_start, trim_end, split_points, segments)

    def set_bookmarks(self, bookmarks: list[float]) -> None:
        self._timeline.set_bookmarks(bookmarks)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, total_duration: float) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # Timeline widget
        self._timeline = _TimelineWidget(total_duration)
        self._timeline.timeline_changed.connect(self.profile_changed.emit)
        layout.addWidget(self._timeline)

        # --- Controls row ---
        controls = QFrame()
        controls.setObjectName("toolbarIsland")
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(8, 6, 8, 6)
        ctrl_layout.setSpacing(8)

        # Split button
        split_btn = QPushButton("Split at Playhead (S)")
        split_btn.setToolTip("Split the segment at the current playback position")
        split_btn.clicked.connect(
            lambda: self._timeline.split_at_playhead(self._timeline._total / 2)
        )
        ctrl_layout.addWidget(split_btn)

        ctrl_layout.addStretch()

        # Segment speed
        ctrl_layout.addWidget(QLabel("Segment speed:"))
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(_SPEED_OPTIONS)
        self._speed_combo.setCurrentText("1")
        self._speed_combo.currentTextChanged.connect(self._on_speed_changed)
        ctrl_layout.addWidget(self._speed_combo)

        layout.addWidget(controls)

        # Segment count label
        self._info_label = QLabel("1 segment")
        self._info_label.setObjectName("cardMeta")
        layout.addWidget(self._info_label)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_speed_changed(self, text: str) -> None:
        """Apply speed to the currently selected (or last) segment."""
        seg_idx = self._timeline.selected_segment()
        if seg_idx is None:
            seg_idx = self._timeline.segment_count() - 1
        try:
            speed = float(text)
            self._timeline.set_speed(seg_idx, speed)
        except ValueError:
            logger.debug("Invalid speed value: %s", text)


def _fmt(seconds: float) -> str:
    """Format seconds as M:SS."""
    total = int(max(seconds, 0))
    return f"{total // 60}:{total % 60:02d}"
