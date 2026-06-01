"""Recording page — centered layout with pill record button, mode selector,
hotkey reminder, last recordings strip, and empty state.

Layout (ui-revamp Phase 7)::

    ┌────────────────────────────────────────┐
    │          Record                        │
    │                                        │
    │     [  ● Start Recording  ]            │  120×48 pill
    │                                        │
    │   [Game] [Desktop] [Window]            │  mode selector
    │                                        │
    │   Press Ctrl+F12 to start/stop         │  hotkey reminder
    │                                        │
    │   ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐           │  last 5 strip
    │   └──┘ └──┘ └──┘ └──┘ └──┘           │
    └────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class RecordingPage(QWidget):
    """Recording page — ready state with pill button, mode selector, and last recordings.

    Signals:
        start_recording: User clicked Record.
        stop_recording: User clicked Stop.
        save_clip: User clicked Save Clip with duration.
    """

    start_recording = pyqtSignal()
    stop_recording = pyqtSignal()
    save_clip = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recording = False
        self._elapsed = 0
        self._mode = "game"  # game / desktop / window
        self._store: "Store | None" = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title
        title = QLabel("Record")
        title.setObjectName("pageTitle")
        title.setContentsMargins(16, 12, 16, 0)
        layout.addWidget(title)

        # Scrollable center content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(16, 32, 16, 32)

        # ── Record button (large pill) ─────────────────────────────────
        self._record_btn = QPushButton("●  Start Recording")
        self._record_btn.setFixedSize(120, 48)
        self._record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: #ffffff;
                border: none;
                border-radius: 24px;
                font-size: 15px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #5ab0ff;
            }
            QPushButton:pressed {
                background-color: #3a8eef;
            }
        """)
        self._record_btn.clicked.connect(self._on_record_clicked)
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row.addWidget(self._record_btn)
        content_layout.addLayout(btn_row)

        # ── Status text ────────────────────────────────────────────────
        self._status_label = QLabel("Ready to record")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "font-size: 13px; color: var(--text-secondary); background: transparent;"
        )
        content_layout.addWidget(self._status_label)

        # ── Recording pulse timer ──────────────────────────────────────
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(100)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)
        self._pulse_phase = 0.0

        # ── Elapsed timer ──────────────────────────────────────────────
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._on_elapsed_tick)

        # ── Mode selector pills ────────────────────────────────────────
        mode_row = QHBoxLayout()
        mode_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_row.setSpacing(8)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        for mode_name, mode_key in [("Game", "game"), ("Desktop", "desktop"), ("Window", "window")]:
            btn = QToolButton()
            btn.setText(mode_name)
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QToolButton {
                    border: 1px solid #3d3d3d;
                    border-radius: 14px;
                    padding: 4px 16px;
                    font-size: 12px;
                    color: var(--text-secondary);
                    background: transparent;
                }
                QToolButton:checked {
                    background-color: #4a9eff;
                    border-color: #4a9eff;
                    color: #ffffff;
                }
                QToolButton:hover:!checked {
                    border-color: #555555;
                }
            """)
            btn.setProperty("_mode", mode_key)
            btn.clicked.connect(lambda checked, m=mode_key: self._set_mode(m))
            self._mode_group.addButton(btn)
            mode_row.addWidget(btn)

        # Default to Game
        self._mode_group.buttons()[0].setChecked(True)
        content_layout.addLayout(mode_row)

        # ── Hotkey reminder ────────────────────────────────────────────
        hotkey_lbl = QLabel("Press Ctrl+F12 to start/stop")
        hotkey_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hotkey_lbl.setStyleSheet(
            "font-size: 11px; color: var(--text-muted); background: transparent;"
        )
        content_layout.addWidget(hotkey_lbl)

        # ── Last recordings strip ──────────────────────────────────────
        self._last_strip_title = QLabel("Recent Recordings")
        self._last_strip_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._last_strip_title.setStyleSheet(
            "font-size: 12px; color: var(--text-secondary); background: transparent;"
        )
        self._last_strip_title.setVisible(False)
        content_layout.addWidget(self._last_strip_title)

        self._last_strip = QWidget()
        self._last_strip.setVisible(False)
        self._last_strip_layout = QHBoxLayout(self._last_strip)
        self._last_strip_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._last_strip_layout.setSpacing(8)
        self._last_strip_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._last_strip)

        # ── Empty state ────────────────────────────────────────────────
        self._empty_state = self._build_empty_state()
        self._empty_state.setVisible(False)
        content_layout.addWidget(self._empty_state)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

    # ==================================================================
    # Mode setter
    # ==================================================================

    def _set_mode(self, mode: str) -> None:
        self._mode = mode

    def mode(self) -> str:
        return self._mode

    def hideEvent(self, event) -> None:
        """Stop pulse and elapsed timers when page is hidden."""
        self._pulse_timer.stop()
        self._elapsed_timer.stop()
        super().hideEvent(event)

    def set_ready(self) -> None:
        self._recording = False
        self._pulse_timer.stop()
        self._elapsed_timer.stop()
        self._record_btn.setText("●  Start Recording")
        self._record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff; color: #ffffff;
                border: none; border-radius: 24px;
                font-size: 15px; font-weight: 600;
            }
            QPushButton:hover { background-color: #5ab0ff; }
            QPushButton:pressed { background-color: #3a8eef; }
        """)
        self._status_label.setText("Ready to record")
        self._status_label.setStyleSheet(
            "font-size: 13px; color: var(--text-secondary); background: transparent;"
        )

    def set_recording(self, fps: int = 60) -> None:
        self._recording = True
        self._elapsed = 0
        self._record_btn.setText("■  Stop Recording")
        self._pulse_phase = 0.0
        self._pulse_timer.start()
        self._elapsed_timer.start()
        self._status_label.setText("Recording… 00:00")
        self._status_label.setStyleSheet(
            "font-size: 13px; color: var(--accent-red); background: transparent;"
        )

    def update_last_strip(self, clips: list[dict]) -> None:
        """Populate the last-5 recordings strip with mini thumbnail cards."""
        # Clear existing widgets
        while self._last_strip_layout.count():
            item = self._last_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not clips:
            self._last_strip_title.setVisible(False)
            self._last_strip.setVisible(False)
            return

        self._last_strip_title.setVisible(True)
        self._last_strip.setVisible(True)

        for clip in clips[:5]:
            card = QWidget()
            card.setFixedSize(120, 80)
            card.setStyleSheet(
                "background-color: #242424; border: 1px solid #3d3d3d;border-radius: 4px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(4, 4, 4, 4)
            card_layout.setSpacing(2)

            thumb_label = QLabel()
            thumb_path = clip.get("thumb_path", "")
            if thumb_path:
                pixmap = QPixmap(thumb_path)
                if not pixmap.isNull():
                    thumb_label.setPixmap(
                        pixmap.scaled(
                            112,
                            50,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            thumb_label.setFixedSize(112, 50)
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setStyleSheet("background: transparent; border: none;")
            card_layout.addWidget(thumb_label)

            name_label = QLabel(clip.get("stem", "")[:16])
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet(
                "font-size: 9px; color: var(--text-secondary);"
                " background: transparent; border: none;"
            )
            card_layout.addWidget(name_label)

            self._last_strip_layout.addWidget(card)

    def set_store(self, store: "Store") -> None:
        self._store = store

    def is_recording(self) -> bool:
        return self._recording

    # ==================================================================
    # Slots
    # ==================================================================

    def _on_record_clicked(self) -> None:
        if self._recording:
            self.stop_recording.emit()
        else:
            self.start_recording.emit()

    def _on_pulse_tick(self) -> None:
        self._pulse_phase += 0.08
        # Pulse opacity between 0.7 and 1.0
        opacity = 0.7 + 0.3 * (math.sin(self._pulse_phase) * 0.5 + 0.5)
        r, g, b = 248, 113, 113  # #f87171
        self._record_btn.setStyleSheet(
            f"QPushButton {{"
            f"background-color: rgba({r},{g},{b},{opacity:.2f});"
            f"color: #ffffff; border: none; border-radius: 24px;"
            f"font-size: 15px; font-weight: 600; }}"
            f"QPushButton:hover {{ background-color:"
            f" rgba({r},{g},{b},{min(1.0, opacity + 0.1):.2f}); }}"
        )

    def _on_elapsed_tick(self) -> None:
        self._elapsed += 1
        mins = self._elapsed // 60
        secs = self._elapsed % 60
        self._status_label.setText(f"Recording… {mins:02d}:{secs:02d}")

    # ==================================================================
    # Empty state
    # ==================================================================

    def _build_empty_state(self) -> QWidget:
        from moment.ui.resources import load_icon

        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon_lbl = QLabel()
        icon = load_icon("empty-recording", "#555555")
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(64, 64))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        heading = QLabel("No recordings yet")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            "font-size: 16px; color: var(--text-secondary); background: transparent;"
        )
        layout.addWidget(heading)

        sub = QLabel("Press Ctrl+F12 or click the button above")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("font-size: 13px; color: var(--text-muted); background: transparent;")
        layout.addWidget(sub)

        return widget
