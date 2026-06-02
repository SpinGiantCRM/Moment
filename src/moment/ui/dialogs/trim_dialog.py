"""Trim dialog — dual-handle timeline for setting in/out points.

Provides a visual timeline with draggable markers for Mark In (blue)
and Mark Out (orange).  The region between handles is highlighted;
crossed handles turn red and disable Apply.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from PyQt6.QtMultimedia import QMediaPlayer

logger = logging.getLogger(__name__)


class TrimDialog(QDialog):
    """Trim dialog with dual-handle timeline widget.

    Signals:
        trim_applied(float, float): Emitted with (start, end) in seconds
            when the user clicks Apply.

    Keyboard shortcuts:
        I = Mark In, O = Mark Out, P = Preview, Enter = Apply, Esc = Cancel
    """

    trim_applied = pyqtSignal(float, float)

    def __init__(
        self,
        duration: float = 0.0,
        start: float = 0.0,
        end: float | None = None,
        parent=None,
        player: "QMediaPlayer | None" = None,
    ) -> None:
        """Args:
        duration: Total clip duration in seconds.
        start: Initial trim start in seconds.
        end: Initial trim end in seconds (defaults to *duration*).
        parent: Parent widget.
        player: Optional QMediaPlayer for Mark In/Out buttons to
            read the current playback position from.
        """
        super().__init__(parent)
        self._player: Any | None = player
        self._duration = max(duration, 0.1)
        self._start = max(start, 0.0)
        self._end = min(end if end is not None else self._duration, self._duration)

        self.setWindowTitle("Trim Clip")
        self.setMinimumSize(600, 250)
        self.setModal(True)

        # --- Timeline widget ---
        from moment.ui.widgets.timeline_editor import TimelineEditor

        self._timeline = TimelineEditor(self._duration, self._start, self._end)
        self._timeline.trim_changed.connect(self._on_trim_changed)

        # --- Time labels ---
        time_layout = QHBoxLayout()
        self._in_label = QLabel(f"In: {_format_time(self._start)}")
        self._in_label.setObjectName("cardMeta")
        self._out_label = QLabel(f"Out: {_format_time(self._end)}")
        self._out_label.setObjectName("cardMeta")
        self._duration_label = QLabel(f"Duration: {_format_time(self._end - self._start)}")
        self._duration_label.setObjectName("cardMeta")
        time_layout.addWidget(self._in_label)
        time_layout.addStretch()
        time_layout.addWidget(self._duration_label)
        time_layout.addStretch()
        time_layout.addWidget(self._out_label)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        mark_in_btn = QPushButton("Mark In")
        mark_in_btn.clicked.connect(self._mark_in)
        btn_layout.addWidget(mark_in_btn)

        mark_out_btn = QPushButton("Mark Out")
        mark_out_btn.clicked.connect(self._mark_out)
        btn_layout.addWidget(mark_out_btn)

        preview_btn = QPushButton("Preview Trim")
        preview_btn.clicked.connect(self._preview)
        btn_layout.addWidget(preview_btn)

        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(skip_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setObjectName("accent")
        self._apply_btn.clicked.connect(self._apply)
        self._apply_btn.setEnabled(self._start < self._end)
        btn_layout.addWidget(self._apply_btn)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        layout.addWidget(self._timeline)
        layout.addLayout(time_layout)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_trim_changed(self, start: float, end: float) -> None:
        """Update labels when the timeline handles move."""
        self._start = start
        self._end = end
        valid = start < end
        self._in_label.setText(f"In: {_format_time(start)}")
        self._out_label.setText(f"Out: {_format_time(end)}")
        self._duration_label.setText(f"Duration: {_format_time(end - start) if valid else '—'}")
        self._apply_btn.setEnabled(valid)

    def _mark_in(self) -> None:
        """Set the In point from the current playback position.

        Reads ``self._player.position()`` (milliseconds), converts to
        seconds, clamps to the valid range, and updates the timeline
        handle and labels.  No-op if no player is available.
        """
        if self._player is None:
            logger.debug("Mark In: no player available")
            return
        if self._player.duration() <= 0:
            logger.debug("Mark In: no media loaded")
            return

        pos_s = self._player.position() / 1000.0
        # Clamp: 0.0 ≤ pos < out point (leave a tiny gap so handles don't cross)
        pos_s = max(0.0, min(pos_s, self._end - 0.01))

        self._timeline.set_range(pos_s, self._end)
        self._on_trim_changed(pos_s, self._end)
        logger.debug("Mark In at %.1fs", pos_s)

    def _mark_out(self) -> None:
        """Set the Out point from the current playback position.

        Reads ``self._player.position()`` (milliseconds), converts to
        seconds, clamps to the valid range, and updates the timeline
        handle and labels.  No-op if no player is available.
        """
        if self._player is None:
            logger.debug("Mark Out: no player available")
            return
        if self._player.duration() <= 0:
            logger.debug("Mark Out: no media loaded")
            return

        pos_s = self._player.position() / 1000.0
        # Clamp: in point < pos ≤ duration
        pos_s = max(self._start + 0.01, min(pos_s, self._duration))

        self._timeline.set_range(self._start, pos_s)
        self._on_trim_changed(self._start, pos_s)
        logger.debug("Mark Out at %.1fs", pos_s)

    def _preview(self) -> None:
        """Preview the trimmed region."""
        logger.debug("Preview: %.1fs → %.1fs", self._start, self._end)

    def _apply(self) -> None:
        """Emit the trim range and accept the dialog."""
        if self._start < self._end:
            self.trim_applied.emit(self._start, self._end)
        self.accept()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def trim_start(self) -> float:
        """Current Mark In point in seconds."""
        return self._start

    @property
    def trim_end(self) -> float:
        """Current Mark Out point in seconds."""
        return self._end

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Handle keyboard shortcuts."""

        key = event.key()
        if key == Qt.Key.Key_I:
            self._mark_in()
        elif key == Qt.Key.Key_O:
            self._mark_out()
        elif key == Qt.Key.Key_P:
            self._preview()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._apply()
        elif key == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_time(seconds: float) -> str:
    """Format seconds as ``M:SS`` or ``H:MM:SS``."""
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"
