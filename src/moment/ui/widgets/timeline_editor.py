"""Timeline editor widget — dual-handle range selector.

A custom-painted widget that shows a horizontal bar with draggable
Mark In (blue) and Mark Out (orange) handles.  The region between
handles is highlighted; crossed handles turn red.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QWidget

# Visual constants
_HANDLE_W = 6  # handle width in pixels
_BAR_H = 24
_MIN_REGION = 0.02  # minimum region as fraction of total length


class TimelineEditor(QWidget):
    """A horizontal timeline with two draggable handles.

    Signals:
        trim_changed(float, float): Emitted with (start, end) in seconds
            whenever the handles are moved.
    """

    trim_changed = pyqtSignal(float, float)

    def __init__(
        self,
        total_duration: float,
        start: float = 0.0,
        end: float | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._total = max(total_duration, 0.1)
        self._start = max(start, 0.0)
        self._end = min(end if end is not None else self._total, self._total)

        self._dragging: str | None = None  # "in", "out", or None
        self._hover: str | None = None

        self.setMinimumHeight(_BAR_H + 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def trim_start(self) -> float:
        return self._start

    @property
    def trim_end(self) -> float:
        return self._end

    def set_range(self, start: float, end: float) -> None:
        """Set the trim range programmatically."""
        self._start = max(start, 0.0)
        self._end = min(end, self._total)
        self.update()

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def _track_rect(self) -> QRectF:
        """Return the drawable area (with padding for handles)."""
        margin = _HANDLE_W
        return QRectF(
            margin,
            self.height() / 2 - _BAR_H / 2,
            self.width() - 2 * margin,
            _BAR_H,
        )

    def _pos_to_frac(self, x: float) -> float:
        """Convert a pixel x-coordinate to a 0.0–1.0 fraction."""
        r = self._track_rect()
        frac = (x - r.x()) / max(r.width(), 1)
        return max(0.0, min(1.0, frac))

    def _frac_to_x(self, frac: float) -> float:
        """Convert a 0.0–1.0 fraction to a pixel x-coordinate."""
        r = self._track_rect()
        return r.x() + frac * r.width()

    def _handle_x(self, frac: float) -> float:
        """Center position for a handle at the given fraction."""
        return self._frac_to_x(frac)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = self._track_rect()
        crossed = self._start >= self._end

        # Track background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2a2a2a"))
        p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 4, 4)

        # Selected region
        if not crossed:
            x1 = self._handle_x(self._start / self._total)
            x2 = self._handle_x(self._end / self._total)
            region = QRectF(x1, r.y(), x2 - x1, r.height())
            p.setBrush(QColor(96, 165, 250, 40))
            p.drawRect(region)

        # Handles
        for name, frac, color in [
            ("in", self._start / self._total, "#60a5fa"),
            ("out", self._end / self._total, "#fb923c"),
        ]:
            hx = self._handle_x(frac)
            if crossed:
                color = "#f87171"  # red when crossed
            is_hover = self._hover == name
            is_drag = self._dragging == name

            # Handle bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(
                QRectF(hx - _HANDLE_W / 2, r.y() - 2, _HANDLE_W, r.height() + 4),
                2,
                2,
            )

            # Glow on hover/drag
            if is_hover or is_drag:
                p.setBrush(Qt.BrushStyle.NoBrush)
                glow = QPen(QColor(color))
                glow.setWidth(2)
                p.setPen(glow)
                p.drawRoundedRect(
                    QRectF(hx - _HANDLE_W / 2 - 2, r.y() - 4, _HANDLE_W + 4, r.height() + 8),
                    3,
                    3,
                )

        # Time labels below handles
        p.setPen(QColor("#a1a1aa"))
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)

        start_text = _fmt(self._start)
        end_text = _fmt(self._end)

        p.drawText(
            QRectF(self._handle_x(self._start / self._total) - 40, r.bottom() + 4, 80, 16),
            Qt.AlignmentFlag.AlignCenter,
            start_text,
        )
        p.drawText(
            QRectF(self._handle_x(self._end / self._total) - 40, r.bottom() + 4, 80, 16),
            Qt.AlignmentFlag.AlignCenter,
            end_text,
        )

    def sizeHint(self) -> QSize:
        return QSize(400, _BAR_H + 36)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def _hit_test(self, pos_x: float) -> str | None:
        """Determine which handle (if any) is under the cursor."""
        in_x = self._handle_x(self._start / self._total)
        out_x = self._handle_x(self._end / self._total)

        if abs(pos_x - in_x) <= _HANDLE_W + 4:
            return "in"
        if abs(pos_x - out_x) <= _HANDLE_W + 4:
            return "out"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_test(event.position().x())
            if hit is not None:
                self._dragging = hit
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                # Click in the empty area — move nearest handle
                frac = self._pos_to_frac(event.position().x())
                time = frac * self._total
                dist_in = abs(time - self._start)
                dist_out = abs(time - self._end)
                self._dragging = "in" if dist_in <= dist_out else "out"
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                self._update_handle(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is not None:
            self._update_handle(event.position().x())
        else:
            hit = self._hit_test(event.position().x())
            if hit != self._hover:
                self._hover = hit
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor if hit else Qt.CursorShape.PointingHandCursor
                )
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = None
        self.setCursor(
            Qt.CursorShape.SizeHorCursor if self._hover else Qt.CursorShape.PointingHandCursor
        )
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def _update_handle(self, pos_x: float) -> None:
        """Move the currently dragged handle to *pos_x*."""
        frac = self._pos_to_frac(pos_x)
        time = frac * self._total

        if self._dragging == "in":
            # Don't let start cross end (but allow crossing to show red)
            self._start = max(0.0, min(time, self._end + (_MIN_REGION * self._total)))
            self._start = min(self._start, self._total)
        elif self._dragging == "out":
            self._end = max(self._start, min(time, self._total))

        self.trim_changed.emit(self._start, self._end)
        self.update()


def _fmt(seconds: float) -> str:
    """Format seconds as ``M:SS``."""
    total = int(max(seconds, 0))
    return f"{total // 60}:{total % 60:02d}"
