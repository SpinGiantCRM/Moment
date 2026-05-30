"""Progress ring — circular indeterminate progress indicator.

A 48×48 custom-painted arc that animates via QPropertyAnimation on
``span_angle`` (0→360°, 30 fps, looped).  Three visual states:

- ``QUEUED``: full orange arc, no animation.
- ``ENCODING``: spinning blue arc.
- ``DONE``: snaps to full green arc, fades out over 500ms.

Usage::

    ring = ProgressRing()
    ring.set_state("ENCODING")
    # ... later:
    ring.set_state("DONE")
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from moment.ui.resources import color

_SIZE = 48
_STROKE = 3
_RADIUS = (_SIZE // 2) - _STROKE - 2
_CENTER = _SIZE // 2


class ProgressRing(QWidget):
    """Circular progress indicator for encode/upload status."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_SIZE, _SIZE)
        self.setStyleSheet("background: transparent;")

        self._span_angle: int = 0
        self._start_angle: int = 90
        self._state: str = "QUEUED"
        self._opacity: float = 1.0

        # Colors
        self._arc_color = QColor(color("--accent-blue"))
        self._bg_color = QColor(color("--bg-inset"))
        self._bg_color.setAlpha(80)

        # Spin animation
        self._anim = QPropertyAnimation(self, b"_spin_value", self)
        self._anim.setDuration(1000)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360 * 16)  # 360 degrees in 1/16th degree units
        self._anim.setLoopCount(-1)

        # Fade-out timer for DONE state
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._start_fade)

    # ------------------------------------------------------------------
    # Animated property for spin
    # ------------------------------------------------------------------

    @pyqtProperty(int)
    def _spin_value(self) -> int:
        return self._start_angle

    @_spin_value.setter  # type: ignore[no-redef]
    def _spin_value(self, val: int) -> None:
        self._start_angle = val % (360 * 16)
        self.update()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Update the visual state.

        Args:
            state: ``"QUEUED"``, ``"ENCODING"``, or ``"DONE"``.
        """
        self._state = state.upper()

        if self._state == "QUEUED":
            self._anim.stop()
            self._span_angle = 360 * 16
            self._arc_color = QColor(color("--accent-orange"))
            self._opacity = 1.0
            self.setVisible(True)

        elif self._state == "ENCODING":
            self._span_angle = 270 * 16  # ~3/4 arc for animation
            self._arc_color = QColor(color("--accent-blue"))
            self._opacity = 1.0
            self.setVisible(True)
            self._anim.start()

        elif self._state == "DONE":
            self._anim.stop()
            self._start_angle = 90 * 16
            self._span_angle = 360 * 16  # full circle
            self._arc_color = QColor(color("--accent-green"))
            self._opacity = 1.0
            self.setVisible(True)
            self._fade_timer.start(500)

        self.update()

    def _start_fade(self) -> None:
        """Begin opacity fade-out."""
        if hasattr(self, "_fade_anim") and self._fade_anim.state() == QPropertyAnimation.State.Running:
            self._fade_anim.stop()
        self._fade_anim = QPropertyAnimation(self, b"_opacity_prop", self)
        self._fade_anim.setDuration(500)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    @pyqtProperty(float)
    def _opacity_prop(self) -> float:
        return self._opacity

    @_opacity_prop.setter  # type: ignore[no-redef]
    def _opacity_prop(self, val: float) -> None:
        self._opacity = val
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        rect = QRectF(
            _CENTER - _RADIUS,
            _CENTER - _RADIUS,
            _RADIUS * 2,
            _RADIUS * 2,
        )

        # Background track
        painter.setPen(QPen(self._bg_color, _STROKE, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, 0, 360 * 16)

        # Foreground arc
        painter.setPen(QPen(self._arc_color, _STROKE, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, self._start_angle, self._span_angle)

        painter.end()
