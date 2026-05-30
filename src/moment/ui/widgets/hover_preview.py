"""Hover preview — thumbnail popup that appears after hovering over a clip card.

A 360×203px frameless tool window positioned above/below the hovered card.
Shows a scaled thumbnail with rounded corners.  Delay of 500ms before
appearing; auto-closes after 5s or on mouse leave.

Usage::

    preview = HoverPreviewWidget(thumb_path="/path/to/thumb.jpg", parent=card)
    preview.show_above(target_rect)
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QRect,
    Qt,
    QTimer,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color

_POPUP_W = 360
_POPUP_H = 203
_IMG_W = 356
_IMG_H = 199
_RADIUS = 4
_DELAY_MS = 500
_AUTO_CLOSE_MS = 5000
_OFFSET_Y = 10  # gap from card


class HoverPreviewWidget(QWidget):
    """Frameless popup showing a scaled clip thumbnail.

    Created on hover and destroyed on leave — not persistent.  Uses
    ``WA_ShowWithoutActivating`` to avoid stealing focus.
    """

    def __init__(
        self,
        thumb_path: Path | str | None = None,
        title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(None)  # no parent — frameless tool window
        self.setFixedSize(_POPUP_W, _POPUP_H)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(f"""
            background-color: {color('--bg-surface')};
            border-radius: {_RADIUS}px;
        """)

        self._parent_widget = parent
        self._delay_timer = QTimer(self)
        self._delay_timer.setSingleShot(True)
        self._delay_timer.setInterval(_DELAY_MS)
        self._delay_timer.timeout.connect(self._show_preview)

        self._auto_close = QTimer(self)
        self._auto_close.setSingleShot(True)
        self._auto_close.setInterval(_AUTO_CLOSE_MS)
        self._auto_close.timeout.connect(self.close)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # Thumbnail label
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_IMG_W, _IMG_H)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._thumb_label)

        # Load thumbnail
        if thumb_path is not None and thumb_path:
            path = Path(thumb_path) if isinstance(thumb_path, str) else thumb_path
            if path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        _IMG_W, _IMG_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    # Round corners on the pixmap
                    rounded = QPixmap(scaled.size())
                    rounded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(rounded)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    clip = QPainterPath()
                    clip.addRoundedRect(
                        0, 0, scaled.width(), scaled.height(), _RADIUS, _RADIUS
                    )
                    p.setClipPath(clip)
                    p.drawPixmap(0, 0, scaled)
                    p.end()
                    self._thumb_label.setPixmap(rounded)
                else:
                    self._show_placeholder()
            else:
                self._show_placeholder()
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        """Show a grey placeholder."""
        placeholder = QPixmap(_IMG_W, _IMG_H)
        placeholder.fill(QColor(color("--bg-elevated")))
        self._thumb_label.setPixmap(placeholder)

    # ------------------------------------------------------------------
    # Show / position
    # ------------------------------------------------------------------

    def schedule_show(self, target_rect: QRect) -> None:
        """Start the 500ms delay timer.  *target_rect* is the card's screen rect."""
        self._target_rect = target_rect
        self._delay_timer.start()

    def cancel(self) -> None:
        """Cancel the pending show (called on mouse leave)."""
        self._delay_timer.stop()
        self._auto_close.stop()

    def _show_preview(self) -> None:
        """Position and show the popup."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_geom: QRect = screen.availableGeometry()

        # Position: try above the card, fall back to below
        x = self._target_rect.center().x() - _POPUP_W // 2
        # Clamp X to screen
        x = max(screen_geom.left(), min(x, screen_geom.right() - _POPUP_W))

        # Try above
        y = self._target_rect.top() - _POPUP_H - _OFFSET_Y
        if y < screen_geom.top():
            # Fall back: below
            y = self._target_rect.bottom() + _OFFSET_Y

        self.move(x, y)
        self.show()
        self._auto_close.start()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def enterEvent(self, event: object) -> None:
        """Pause auto-close on hover."""
        super().enterEvent(event)
        self._auto_close.stop()

    def leaveEvent(self, event: object) -> None:
        """Restart auto-close on leave."""
        super().leaveEvent(event)
        self._auto_close.start()
