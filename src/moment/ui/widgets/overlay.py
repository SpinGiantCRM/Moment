"""Overlay widget — frameless always-on-top HUD for quick clip saving.

A compact PyQt6 overlay that floats above games with:
- REC indicator + recording duration
- Quick-save buttons (30s, 60s, 120s) with spinner → checkmark feedback
- Recent clips list (last 5)
- Action links (Open Moment, Settings, Close)
- Auto-hide after inactivity (configurable, default 8s)
- Fade-in/out animation (150ms)

Does **not** steal keyboard focus from the game:
- ``WA_ShowWithoutActivating`` — shows without activating
- ``WA_X11NetWmWindowTypeDock`` — KWin treats as dock (no focus)
- ``Qt.Tool`` — stays on top but doesn't appear in taskbar
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Design tokens — import Moment's palette from resources.py at module
# load so the overlay stays in sync with the application theme.
# ---------------------------------------------------------------------------

def _resolve_color(token: str, fallback: str) -> str:
    """Resolve a palette token at import time, falling back to the hex value."""
    try:
        from moment.ui.resources import color

        return color(token)
    except ImportError:
        return fallback


_COLOR_BG = _resolve_color("--bg-window", "#3c3c3c")
_COLOR_BG_LIGHTER = _resolve_color("--bg-elevated", "#404040")
_COLOR_ACCENT = _resolve_color("--accent-blue", "#60a5fa")
_COLOR_REC = _resolve_color("--accent-red", "#ef4444")
_COLOR_TEXT = _resolve_color("--text-primary", "#d9d9d9")
_COLOR_TEXT_MUTED = _resolve_color("--text-secondary", "#a1a1aa")
_COLOR_SUCCESS = _resolve_color("--accent-green", "#4ade80")
_COLOR_BORDER = _resolve_color("--bg-hover", "#555555")

_OVERLAY_WIDTH = 440
_OVERLAY_HEIGHT = 360
_FADE_DURATION = 150  # ms
_AUTO_HIDE_DEFAULT = 8  # seconds
_REC_DOT_SIZE = 8


class _SaveButton(QPushButton):
    """A quick-save button with three visual states: idle, saving, done."""

    def __init__(self, label: str, duration: int, parent: QWidget | None = None) -> None:
        super().__init__(label, parent)
        self.duration = duration
        self._state: str = "idle"  # idle | saving | done
        self._original_label = label
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {_COLOR_BG_LIGHTER};
                color: {_COLOR_TEXT};
                border: 1px solid {_COLOR_BORDER};
                border-radius: 6px;
                padding: 8px 6px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: #555;
                border-color: {_COLOR_ACCENT};
            }}
            QPushButton:pressed {{
                background: #333;
            }}
            QPushButton[state="saving"] {{
                background: #3b5998;
                border-color: {_COLOR_ACCENT};
            }}
            QPushButton[state="done"] {{
                background: #14532d;
                border-color: {_COLOR_SUCCESS};
            }}
        """)

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "saving":
            self.setText("Saving…")
        elif state == "done":
            self.setText(f"✓ {self._original_label}")
        else:
            self.setText(self._original_label)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def reset(self) -> None:
        self.set_state("idle")


class _RecentClipRow(QFrame):
    """A single row in the recent clips list."""

    clicked = pyqtSignal(str)  # stem

    def __init__(self, stem: str, timestamp: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stem = stem
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            _RecentClipRow {{
                background: transparent;
                border-radius: 4px;
            }}
            _RecentClipRow:hover {{
                background: {_COLOR_BG_LIGHTER};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)

        name_lbl = QLabel(stem)
        name_lbl.setStyleSheet(f"color: {_COLOR_TEXT}; font-size: 12px;")
        layout.addWidget(name_lbl, 1)

        time_lbl = QLabel(timestamp)
        time_lbl.setStyleSheet(f"color: {_COLOR_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(time_lbl)

    def mousePressEvent(self, event: Any) -> None:
        self.clicked.emit(self._stem)


class _ActionLink(QLabel):
    """Clickable text link in the overlay footer."""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            _ActionLink {{
                color: {_COLOR_ACCENT};
                font-size: 12px;
                padding: 2px;
            }}
            _ActionLink:hover {{
                color: #93c5fd;
                text-decoration: underline;
            }}
        """)

    def mousePressEvent(self, event: Any) -> None:
        self.clicked.emit()


# ===========================================================================
# Overlay
# ===========================================================================


class Overlay(QWidget):
    """Frameless always-on-top HUD for quick clip saving.

    Shows on hotkey press. Auto-hides after inactivity. Fades in/out.

    Signals:
        save_requested(duration_seconds): User clicked a quick-save button.
        open_moment: User clicked "Open Moment".
        open_settings: User clicked "Settings".
        close_overlay: User clicked "Close" or auto-hide triggered.

    Typical usage::

        overlay = Overlay(recent_clips=[("clip1.mkv", "10s ago")])
        overlay.save_requested.connect(gsr_controller.save_replay)
        overlay.show_overlay()
    """

    save_requested = pyqtSignal(int)  # duration_seconds
    open_moment = pyqtSignal()
    open_settings = pyqtSignal()
    close_overlay = pyqtSignal()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        recent_clips: list[tuple[str, str]] | None = None,
        auto_hide_seconds: int = _AUTO_HIDE_DEFAULT,
        parent: QWidget | None = None,
    ) -> None:
        """Args:
            recent_clips: List of (stem, relative_time) for the recent list.
            auto_hide_seconds: Seconds of inactivity before auto-hiding.
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._auto_hide_seconds = auto_hide_seconds
        self._duration_seconds = 0  # GSR uptime
        self._showing = False

        # Window flags
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Try to set dock type via X11 property (best-effort)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_X11NetWmWindowTypeDock)
        except Exception:  # nosec B110
            pass

        self.setFixedSize(_OVERLAY_WIDTH, _OVERLAY_HEIGHT)

        # --- Opacity for fade animations ---
        self._opacity: float = 1.0

        # --- Build UI ---
        self._build_ui(recent_clips or [])

        # --- Auto-hide timer ---
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)

        # --- Duration update timer ---
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._on_duration_tick)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, value: float) -> None:
        self._opacity = value
        self.setWindowOpacity(value)

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_overlay(self) -> None:
        """Show the overlay with a fade-in animation and reset the auto-hide timer."""
        if self._showing:
            self._reset_auto_hide()
            return

        self._showing = True
        self._position()
        self.show()

        # Fade in
        self._animate_opacity(0.0, 1.0)

        # Start duration timer
        self._duration_timer.start()

        # Start auto-hide
        self._reset_auto_hide()

    def hide_overlay(self) -> None:
        """Hide the overlay with a fade-out animation."""
        if not self._showing:
            return
        self._showing = False

        self._duration_timer.stop()
        self._auto_hide_timer.stop()

        # Reset buttons
        for btn in self._save_buttons:
            btn.reset()

        self._animate_opacity(1.0, 0.0, on_finish=self.hide)

    def toggle(self) -> None:
        """Toggle overlay visibility."""
        if self._showing:
            self.hide_overlay()
        else:
            self.show_overlay()

    def set_recording_duration(self, seconds: int) -> None:
        """Update the displayed recording duration."""
        self._duration_seconds = seconds
        self._update_duration_label()

    def set_recent_clips(self, clips: list[tuple[str, str]]) -> None:
        """Replace the recent clips list.

        Args:
            clips: List of (stem, relative_time) tuples.
        """
        # Clear existing rows
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add new rows (max 5)
        for stem, timestamp in clips[:5]:
            row = _RecentClipRow(stem, timestamp)
            row.clicked.connect(lambda s=stem: logger.info("Recent clip clicked: %s", s))
            self._recent_layout.addWidget(row)

        # If empty, show placeholder
        if not clips:
            placeholder = QLabel("No recent clips")
            placeholder.setStyleSheet(f"color: {_COLOR_TEXT_MUTED}; font-size: 12px; padding: 8px;")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._recent_layout.addWidget(placeholder)

    def set_auto_hide_seconds(self, seconds: int) -> None:
        """Change the auto-hide timeout."""
        self._auto_hide_seconds = max(4, min(15, seconds))

    def show_save_confirmation(self, duration: int) -> None:
        """Show brief confirmation on a save button."""
        for btn in self._save_buttons:
            if btn.duration == duration:
                btn.set_state("saving")
                # After 1s, show checkmark; after 2s more, reset
                QTimer.singleShot(1000, lambda: btn.set_state("done"))
                QTimer.singleShot(3000, lambda: btn.reset() if btn._state == "done" else None)
                break

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, recent_clips: list[tuple[str, str]]) -> None:
        """Build the overlay widget tree."""
        # Outer frame with rounded corners
        self._frame = QFrame(self)
        self._frame.setObjectName("overlay_frame")
        self._frame.setGeometry(0, 0, _OVERLAY_WIDTH, _OVERLAY_HEIGHT)
        self._frame.setStyleSheet(f"""
            #overlay_frame {{
                background: {_COLOR_BG};
                border: 1px solid {_COLOR_BORDER};
                border-radius: 12px;
            }}
        """)

        main_layout = QVBoxLayout(self._frame)
        main_layout.setContentsMargins(20, 14, 20, 14)
        main_layout.setSpacing(10)

        # --- Row 1: REC indicator + duration ---
        header = QHBoxLayout()
        header.setSpacing(8)

        self._rec_dot = QLabel()
        self._rec_dot.setFixedSize(_REC_DOT_SIZE, _REC_DOT_SIZE)
        self._rec_dot.setStyleSheet(f"""
            background: {_COLOR_REC};
            border-radius: {_REC_DOT_SIZE // 2}px;
        """)
        header.addWidget(self._rec_dot)

        rec_label = QLabel("REC")
        rec_label.setStyleSheet(f"color: {_COLOR_REC}; font-size: 13px; font-weight: bold;")
        header.addWidget(rec_label)

        header.addStretch()

        self._duration_label = QLabel("00:00")
        self._duration_label.setStyleSheet(
            f"color: {_COLOR_TEXT}; font-size: 14px; font-weight: 600;"
        )
        header.addWidget(self._duration_label)

        main_layout.addLayout(header)

        # --- Row 2: Quick-save buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._save_buttons: list[_SaveButton] = []
        for label, dur in [("Save 30s", 30), ("Save 60s", 60), ("Save 120s", 120)]:
            btn = _SaveButton(label, dur)
            btn.clicked.connect(lambda checked, d=dur: self._on_save_clicked(d))
            btn_layout.addWidget(btn)
            self._save_buttons.append(btn)

        main_layout.addLayout(btn_layout)

        # --- Row 3: Recent clips ---
        recent_header = QLabel("Recent Clips")
        recent_header.setStyleSheet(
            f"color: {_COLOR_TEXT_MUTED}; font-size: 11px; "
            "font-weight: 600; text-transform: uppercase;"
        )
        main_layout.addWidget(recent_header)

        self._recent_layout = QVBoxLayout()
        self._recent_layout.setSpacing(2)
        main_layout.addLayout(self._recent_layout, 1)

        # Populate recent clips
        self.set_recent_clips(recent_clips)

        # --- Row 4: Separator + action links ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"border: none; background: {_COLOR_BORDER}; max-height: 1px;")
        main_layout.addWidget(sep)

        footer = QHBoxLayout()
        footer.setSpacing(12)

        open_link = _ActionLink("Open Moment")
        open_link.clicked.connect(self.open_moment.emit)
        footer.addWidget(open_link)

        settings_link = _ActionLink("Settings")
        settings_link.clicked.connect(self.open_settings.emit)
        footer.addWidget(settings_link)

        footer.addStretch()

        close_link = _ActionLink("Close  ✕")
        close_link.clicked.connect(self.close_overlay.emit)
        close_link.setStyleSheet(close_link.styleSheet().replace(
            f"color: {_COLOR_ACCENT}",
            f"color: {_COLOR_TEXT_MUTED}",
        ))
        footer.addWidget(close_link)

        main_layout.addLayout(footer)

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position(self) -> None:
        """Position the overlay at bottom-center of the primary screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo: QRect = screen.availableGeometry()
        x = geo.x() + (geo.width() - _OVERLAY_WIDTH) // 2
        y = geo.y() + geo.height() - _OVERLAY_HEIGHT - 40  # 40px from bottom
        self.move(x, y)

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _animate_opacity(
        self,
        from_val: float,
        to_val: float,
        on_finish: "callable[[], None] | None" = None,
    ) -> None:
        """Animate window opacity."""
        self._anim = QPropertyAnimation(self, b"opacity")
        self._anim.setDuration(_FADE_DURATION)
        self._anim.setStartValue(from_val)
        self._anim.setEndValue(to_val)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if on_finish is not None:
            self._anim.finished.connect(on_finish)
        self._anim.start()

    # ------------------------------------------------------------------
    # Auto-hide
    # ------------------------------------------------------------------

    def _reset_auto_hide(self) -> None:
        """Reset the auto-hide countdown."""
        if self._auto_hide_seconds > 0:
            self._auto_hide_timer.start(self._auto_hide_seconds * 1000)

    def _on_auto_hide(self) -> None:
        """Auto-hide timer expired."""
        logger.debug("Overlay auto-hiding after %ds", self._auto_hide_seconds)
        self.close_overlay.emit()

    # ------------------------------------------------------------------
    # Duration ticker
    # ------------------------------------------------------------------

    def _on_duration_tick(self) -> None:
        """Increment recording duration each second."""
        self._duration_seconds += 1
        self._update_duration_label()

    def _update_duration_label(self) -> None:
        """Format and display the recording duration."""
        td = timedelta(seconds=self._duration_seconds)
        total = int(td.total_seconds())
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours:
            self._duration_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self._duration_label.setText(f"{minutes:02d}:{seconds:02d}")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_save_clicked(self, duration: int) -> None:
        """User clicked a quick-save button."""
        logger.info("Overlay: save %ds clicked", duration)
        self.show_save_confirmation(duration)
        self.save_requested.emit(duration)
        # Reset auto-hide so user can see the confirmation
        self._reset_auto_hide()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event: Any) -> None:
        """Override to prevent default painting (transparent background)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The frame handles its own rounded background
        painter.end()
