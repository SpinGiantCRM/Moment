"""Recording page — ready-to-record state and live recording monitor.

Shows a large Record button, FPS counter, and elapsed duration when idle.
During active recording, displays a live preview placeholder with an
animated REC indicator, duration ticker, and stop/save controls.

Includes a "Configure Games" button for manually adding game process
names on Wayland / Flatpak where auto-detection is unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


# Resolve palette token at import time for the recording dot

def _rec_dot_color() -> QColor:
    """Return the accent-red colour from the Moment palette."""
    try:
        from moment.ui.resources import color

        hex_val = color("--accent-red")
        return QColor(hex_val)
    except ImportError:
        return QColor("#f87171")


_REC_DOT_COLOR = _rec_dot_color()


class _RecDot(QLabel):
    """Animated red recording dot with fade-pulse."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase: float = 0.0  # 0.0 → 1.0 cycling
        self._active: bool = False
        self.setFixedSize(14, 14)
        self.setStyleSheet("background: transparent;")
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._on_tick)
        # Timer starts only when animate(True) is called

    def animate(self, active: bool) -> None:
        """Start or stop the pulse animation."""
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _on_tick(self) -> None:
        self._phase = (self._phase + 0.1) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._active:
            alpha = 0.6 + 0.4 * (1.0 - abs(self._phase - 0.5) * 2.0)
        else:
            alpha = 1.0

        # Lerp between accent-red and dark gray for a smooth fade-pulse
        base = _REC_DOT_COLOR
        dark = QColor(68, 68, 68)
        color = QColor(
            int(base.red() * alpha + dark.red() * (1 - alpha)),
            int(base.green() * alpha + dark.green() * (1 - alpha)),
            int(base.blue() * alpha + dark.blue() * (1 - alpha)),
        )
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 12, 12)
        p.end()


class RecordingPage(QWidget):
    """Recording page — ready state and live recording monitor.

    Signals:
        start_recording: User clicked Record.
        stop_recording: User clicked Stop.
        save_clip: User clicked Save Clip with duration.
    """

    start_recording = pyqtSignal()
    stop_recording = pyqtSignal()
    save_clip = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._recording = False
        self._elapsed: int = 0
        self._fps: int = 0
        self._store: "Store | None" = None

        # --- Ready state widget ---
        self._ready_widget = QWidget()
        self._build_ready_state()

        # --- Recording state widget ---
        self._recording_widget = QWidget()
        self._build_recording_state()

        # --- Elapsed timer ---
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._on_elapsed_tick)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        # Title row
        title = QLabel("Record")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # Stack the two states
        layout.addWidget(self._ready_widget, stretch=1)
        layout.addWidget(self._recording_widget, stretch=1)

        # Start in ready state
        self._ready_widget.setVisible(True)
        self._recording_widget.setVisible(False)

    # ==================================================================
    # Ready state
    # ==================================================================

    def _build_ready_state(self) -> None:
        """Build the ready-to-record view with a big Record button."""
        layout = QVBoxLayout(self._ready_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        # Icon
        icon = QLabel("⏺")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "font-size: 48px; color: var(--text-muted);"
        )
        layout.addWidget(icon)

        # Subtitle
        subtitle = QLabel("Ready to record")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 14px;")
        layout.addWidget(subtitle)

        # Big Record button
        self._record_btn = QPushButton("●  Start Recording")
        self._record_btn.setObjectName("accent")
        self._record_btn.setFixedSize(220, 56)
        self._record_btn.setStyleSheet(
            "QPushButton#accent {"
            "   background-color: var(--accent-red);"
            "   color: #ffffff;"
            "   border-radius: 28px;"
            "   font-size: 16px;"
            "   font-weight: 700;"
            "}"
            "QPushButton#accent:hover {"
            "   background-color: #ef4444;"
            "}"
        )
        self._record_btn.clicked.connect(self._on_record_clicked)
        btn_container = QHBoxLayout()
        btn_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_container.addWidget(self._record_btn)
        layout.addLayout(btn_container)

        # Hint row
        hints = QHBoxLayout()
        hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hints.setSpacing(16)

        hint_fps = QLabel("FPS")
        hint_fps.setObjectName("muted")
        hints.addWidget(hint_fps)

        self._ready_fps = QLabel("--")
        self._ready_fps.setStyleSheet(
            "color: var(--text-primary); font-size: 18px; font-weight: 600;"
        )
        hints.addWidget(self._ready_fps)

        hint_dur = QLabel("Duration")
        hint_dur.setObjectName("muted")
        hints.addWidget(hint_dur)

        self._ready_duration = QLabel("00:00")
        self._ready_duration.setStyleSheet(
            "color: var(--text-primary); font-size: 18px; font-weight: 600;"
        )
        hints.addWidget(self._ready_duration)

        layout.addLayout(hints)

        # Manual game configuration button (Wayland/Flatpak)
        game_cfg_row = QHBoxLayout()
        game_cfg_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._configure_games_btn = QPushButton("Configure Games")
        self._configure_games_btn.setObjectName("muted")
        self._configure_games_btn.setStyleSheet(
            "QPushButton { border: 1px solid #3f3f46; border-radius: 6px; "
            "padding: 6px 16px; font-size: 13px; color: #a1a1aa; }"
            "QPushButton:hover { border-color: #71717a; color: #d9d9d9; }"
        )
        self._configure_games_btn.clicked.connect(self._on_configure_games)
        game_cfg_row.addWidget(self._configure_games_btn)
        layout.addLayout(game_cfg_row)

    # ==================================================================
    # Recording state
    # ==================================================================

    def _build_recording_state(self) -> None:
        """Build the live-recording view with REC indicator and controls."""
        layout = QVBoxLayout(self._recording_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        # REC row
        rec_row = QHBoxLayout()
        rec_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_row.setSpacing(10)

        self._rec_dot = _RecDot()
        rec_row.addWidget(self._rec_dot)

        rec_label = QLabel("RECORDING")
        rec_label.setStyleSheet(
            "color: var(--accent-red); font-size: 16px; font-weight: 700;"
        )
        rec_row.addWidget(rec_label)
        layout.addLayout(rec_row)

        # Elapsed time
        self._rec_elapsed = QLabel("00:00")
        self._rec_elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rec_elapsed.setStyleSheet(
            "color: var(--text-primary); font-size: 42px; font-weight: 300;"
        )
        layout.addWidget(self._rec_elapsed)

        # FPS counter
        self._rec_fps_label = QLabel("60 FPS")
        self._rec_fps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rec_fps_label.setObjectName("muted")
        layout.addWidget(self._rec_fps_label)

        # Stop / Save buttons
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.setSpacing(12)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setObjectName("danger")
        self._stop_btn.setFixedSize(120, 44)
        self._stop_btn.setStyleSheet(
            "QPushButton#danger {"
            "   border: 1px solid var(--accent-red);"
            "   color: var(--accent-red);"
            "   border-radius: 8px;"
            "   font-size: 14px;"
            "   font-weight: 600;"
            "}"
            "QPushButton#danger:hover {"
            "   background-color: rgba(248, 113, 113, 0.15);"
            "}"
        )
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self._stop_btn)

        self._save_clip_btn = QPushButton("Save 30s")
        self._save_clip_btn.setFixedSize(120, 44)
        self._save_clip_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: var(--accent-blue);"
            "   color: #ffffff;"
            "   border-radius: 8px;"
            "   font-size: 14px;"
            "   font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "   background-color: #3b82f6;"
            "}"
        )
        self._save_clip_btn.clicked.connect(lambda: self._on_save_clicked(30))
        btn_row.addWidget(self._save_clip_btn)
        layout.addLayout(btn_row)

    def set_store(self, store: "Store") -> None:
        """Set the Store reference (called after init by AppManager)."""
        self._store = store

    # ==================================================================
    # Public API
    # ==================================================================

    def set_ready(self) -> None:
        """Switch to the ready-to-record state."""
        self._recording = False
        self._elapsed_timer.stop()
        self._rec_dot.animate(False)
        self._ready_widget.setVisible(True)
        self._recording_widget.setVisible(False)

    def set_recording(self, fps: int = 60) -> None:
        """Switch to the live-recording state.

        Args:
            fps: Current capture frame rate.
        """
        self._recording = True
        self._elapsed = 0
        self._fps = fps
        self._rec_elapsed.setText("00:00")
        self._rec_fps_label.setText(f"{fps} FPS")
        self._rec_dot.animate(True)
        self._elapsed_timer.start()
        self._ready_widget.setVisible(False)
        self._recording_widget.setVisible(True)

    def is_recording(self) -> bool:
        """Whether the page believes it's currently recording."""
        return self._recording

    # ==================================================================
    # Slots
    # ==================================================================

    def _on_record_clicked(self) -> None:
        """User clicked the big Record button."""
        logger.info("Recording started from page")
        self.start_recording.emit()

    def _on_stop_clicked(self) -> None:
        """User clicked Stop."""
        logger.info("Recording stopped from page")
        self.stop_recording.emit()

    def _on_save_clicked(self, duration: int) -> None:
        """User clicked Save Clip."""
        logger.info("Save %ds clip requested from recording page", duration)
        self.save_clip.emit(duration)

    def _on_configure_games(self) -> None:
        """Open the manual game configuration dialog."""
        from moment.ui.dialogs.manual_game_dialog import ManualGameDialog
        dlg = ManualGameDialog(store=self._store, parent=self)
        dlg.exec()

    def _on_elapsed_tick(self) -> None:
        """Update the elapsed time display."""
        self._elapsed += 1
        mins = self._elapsed // 60
        secs = self._elapsed % 60
        self._rec_elapsed.setText(f"{mins:02d}:{secs:02d}")
