"""Toast notification system — non-blocking popups stacked bottom-right.

Uses QPropertyAnimation for slide-in/out.  Max 3 visible at a time;
the 4th replaces the oldest.  Hover pauses the auto-dismiss timer.

Access the global singleton via ``toast_manager``::

    from moment.ui.widgets.toast import toast_manager
    toast_manager.show_toast("success", "Upload complete", "clip-42.mp4")
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Toast type presets
# ---------------------------------------------------------------------------

_TOAST_PRESETS: dict[str, dict[str, str | int]] = {
    "success":      {"accent": "--accent-green",  "icon": "✓", "duration_ms": 5000},
    "info":         {"accent": "--accent-blue",   "icon": "ℹ", "duration_ms": 4000},
    "warning":      {"accent": "--accent-orange", "icon": "⚠", "duration_ms": 6000},
    "error":        {"accent": "--accent-red",    "icon": "✗", "duration_ms": 8000},
    "copy_success": {"accent": "--accent-green",  "icon": "✓", "duration_ms": 1500},
}

_OFFSET_BOTTOM = 24
_OFFSET_RIGHT = 24
_TOAST_WIDTH = 320
_TOAST_GAP = 8
_MAX_VISIBLE = 3


# ===========================================================================
# ToastWidget — a single toast
# ===========================================================================


class ToastWidget(QFrame):
    """A single toast notification that slides in and auto-dismisses."""

    dismissed = pyqtSignal(object)

    def __init__(
        self,
        toast_type: str,
        title: str,
        body: str = "",
        duration_ms: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        preset = _TOAST_PRESETS.get(toast_type, _TOAST_PRESETS["info"])
        self._duration_ms = duration_ms or int(preset["duration_ms"])
        self._accent_color = color(str(preset["accent"]))
        self._hovered = False
        self._timer: QTimer | None = None
        self._slide_anim: QPropertyAnimation | None = None

        # Appearance
        self.setFixedWidth(_TOAST_WIDTH)
        self.setMinimumHeight(52)
        self.setObjectName("toastWidget")
        self.setStyleSheet(f"""
            #toastWidget {{
                background-color: {color('--bg-surface')};
                border-left: 3px solid {self._accent_color};
                border-radius: 6px;
            }}
        """)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # --- Layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(8)

        # Icon
        self._icon_label = QLabel(str(preset["icon"]))
        self._icon_label.setFixedWidth(18)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._icon_label.setStyleSheet(
            f"color: {self._accent_color}; font-size: 14px; font-weight: bold;"
        )
        layout.addWidget(self._icon_label)

        # Text block
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("toastTitle")
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #d9d9d9;")
        text_layout.addWidget(self._title_label)

        if body:
            self._body_label = QLabel(body)
            self._body_label.setObjectName("toastBody")
            self._body_label.setWordWrap(True)
            self._body_label.setStyleSheet("font-size: 12px; color: #a1a1aa;")
            text_layout.addWidget(self._body_label)

        layout.addLayout(text_layout, 1)

        # Dismiss button
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; color: #757575;
                font-size: 16px; font-weight: bold; padding: 0;
            }
            QPushButton:hover { color: #d9d9d9; }
        """)
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        # Start auto-dismiss timer
        self._start_timer()

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    @pyqtProperty(QPoint)
    def _slide_pos(self) -> QPoint:
        return self.pos()

    @_slide_pos.setter  # type: ignore[no-redef]
    def _slide_pos(self, pos: QPoint) -> None:
        self.move(pos)

    def slide_in(self, target_pos: QPoint) -> None:
        """Animate from off-screen right to *target_pos*."""
        self._stop_animation()
        start = QPoint(target_pos.x() + _TOAST_WIDTH + 40, target_pos.y())
        self.move(start)
        self.show()

        self._slide_anim = QPropertyAnimation(self, b"_slide_pos", self)
        self._slide_anim.setDuration(200)
        self._slide_anim.setStartValue(start)
        self._slide_anim.setEndValue(target_pos)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.start()

    def _stop_animation(self) -> None:
        """Stop any in-progress slide animation."""
        if self._slide_anim is not None and self._slide_anim.state() == QPropertyAnimation.State.Running:
            self._slide_anim.stop()

    def slide_out(self) -> None:
        """Animate off-screen right, then delete."""
        self._stop_animation()
        end = QPoint(self.pos().x() + _TOAST_WIDTH + 40, self.pos().y())
        self._slide_anim = QPropertyAnimation(self, b"_slide_pos", self)
        self._slide_anim.setDuration(150)
        self._slide_anim.setStartValue(self.pos())
        self._slide_anim.setEndValue(end)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_anim.finished.connect(self._on_slide_out_done)
        self._slide_anim.start()

    def _on_slide_out_done(self) -> None:
        self.dismissed.emit(self)
        self.close()

    # ------------------------------------------------------------------
    # Timer / dismiss
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(self._duration_ms)

    def _pause_timer(self) -> None:
        if self._timer is not None and self._timer.isActive():
            self._timer.stop()

    def _resume_timer(self) -> None:
        if self._timer is not None:
            self._timer.start(self._duration_ms)

    def _dismiss(self) -> None:
        """Dismiss this toast (slide-out, then emit dismissed)."""
        if self._timer is not None:
            self._timer.stop()
        self.slide_out()

    # ------------------------------------------------------------------
    # Hover pause support
    # ------------------------------------------------------------------

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._pause_timer()

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._resume_timer()


# ===========================================================================
# ToastManager — global singleton
# ===========================================================================


class ToastManager(QObject):
    """Manages a stack of :class:`ToastWidget` instances.

    Shows up to ``_MAX_VISIBLE`` toasts at once (oldest replaced on overflow).
    Animates slide-in / slide-out.  Toasts are parented to the primary screen.

    This is a singleton — import the pre-built ``toast_manager`` instance::

        from moment.ui.widgets.toast import toast_manager
        toast_manager.show_toast("success", "Done!")
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._toasts: list[ToastWidget] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_toast(
        self,
        toast_type: str,
        title: str,
        body: str = "",
        duration: int | None = None,
    ) -> None:
        """Show a toast notification.

        Args:
            toast_type: One of ``"success"``, ``"info"``, ``"warning"``,
                        ``"error"``, ``"copy_success"``.
            title: Bold header line.
            body: Optional descriptive text.
            duration: Override the default duration in **milliseconds**.
        """
        if toast_type not in _TOAST_PRESETS:
            logger.warning("Unknown toast type %r, defaulting to 'info'", toast_type)
            toast_type = "info"

        duration_ms = duration or int(_TOAST_PRESETS[toast_type]["duration_ms"])

        toast = ToastWidget(toast_type, title, body, duration_ms)
        toast.dismissed.connect(self._on_dismissed)

        # Enforce max visible — dismiss oldest
        if len(self._toasts) >= _MAX_VISIBLE:
            oldest = self._toasts[0]
            oldest._dismiss()
            # It will be removed via _on_dismissed; add new one now anyway

        self._toasts.append(toast)

        # Position at bottom-right
        target = self._calc_position()
        toast.slide_in(target)

    def _calc_position(self) -> QPoint:
        """Compute the bottom-right target position for a new toast."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(100, 100)
        geom: QRect = screen.availableGeometry()
        x = geom.right() - _TOAST_WIDTH - _OFFSET_RIGHT

        # Stack upwards from bottom
        total_height = 0
        for t in self._toasts:
            if t.isVisible():
                total_height += t.height() + _TOAST_GAP
        y = geom.bottom() - _OFFSET_BOTTOM - total_height - 52  # estimate height
        return QPoint(x, max(y, geom.top()))

    def _layout_all(self) -> None:
        """Re-position all visible toasts (called when one is removed)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom: QRect = screen.availableGeometry()
        x = geom.right() - _TOAST_WIDTH - _OFFSET_RIGHT

        y = geom.bottom() - _OFFSET_BOTTOM
        for toast in reversed(self._toasts):
            if not toast.isVisible():
                continue
            y -= toast.height() + _TOAST_GAP
            toast._slide_pos = QPoint(x, y)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_dismissed(self, toast: ToastWidget) -> None:
        """Remove *toast* from the stack and re-layout remaining toasts."""
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout_all()


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

toast_manager = ToastManager()
