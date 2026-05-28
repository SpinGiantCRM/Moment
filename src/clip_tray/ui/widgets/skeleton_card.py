"""Skeleton card — pulse-animated placeholder matching ClipDelegate dimensions.

Used during initial data load on the grid page.  Animates opacity between
0.3 and 1.0 with a 1.5s cycle period.

Usage::

    card = SkeletonCard()
    layout.addWidget(card)
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from clip_tray.ui.resources import color

_CARD_W = 260
_CARD_H = 190
_THUMB_W = 240
_THUMB_H = 135
_THUMB_X = (_CARD_W - _THUMB_W) // 2
_THUMB_Y = 6
_TITLE_W = int(_CARD_W * 0.60)
_TITLE_X = 10
_TITLE_Y = _THUMB_Y + _THUMB_H + 16
_SUBTITLE_W = int(_CARD_W * 0.40)
_SUBTITLE_Y = _TITLE_Y + 14
_LINE_H = 8
_RADIUS = 4


class SkeletonCard(QWidget):
    """A 260×190 pulsing placeholder card."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setStyleSheet(f"background-color: {color('--bg-surface')}; border-radius: 6px;")

        self._opacity_val = 1.0
        self._base_color = QColor(color("--bg-elevated"))

        # Opacity animation: cycle 0.3 ↔ 1.0 with 1.5s period
        self._anim = QPropertyAnimation(self, b"_opacity", self)
        self._anim.setDuration(1500)
        self._anim.setStartValue(0.3)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)  # infinite
        self._anim.start()

    # ------------------------------------------------------------------
    # Animated property
    # ------------------------------------------------------------------

    @pyqtProperty(float)
    def _opacity(self) -> float:
        return self._opacity_val

    @_opacity.setter  # type: ignore[no-redef]
    def _opacity(self, val: float) -> None:
        self._opacity_val = val
        self.update()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color_with_alpha = QColor(self._base_color)
        alpha = int(255 * getattr(self, "_opacity_val", 1.0))
        color_with_alpha.setAlpha(max(30, alpha))
        painter.setBrush(QBrush(color_with_alpha))
        painter.setPen(Qt.PenStyle.NoPen)

        # Thumbnail placeholder
        painter.drawRoundedRect(QRect(_THUMB_X, _THUMB_Y, _THUMB_W, _THUMB_H), _RADIUS, _RADIUS)

        # Title line (60% width)
        painter.drawRoundedRect(QRect(_TITLE_X, _TITLE_Y, _TITLE_W, _LINE_H), 3, 3)

        # Subtitle line (40% width)
        painter.drawRoundedRect(QRect(_TITLE_X, _SUBTITLE_Y, _SUBTITLE_W, _LINE_H // 2), 2, 2)

        painter.end()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_color(self, base_color: QColor) -> None:
        """Change the skeleton fill colour for theme compatibility."""
        self._base_color = base_color
        self.update()
