"""Processing banner — pipeline status indicator between toolbar and page.

A 28px banner showing the current pipeline state (e.g. "Encoding 2/5 clips…").
Appears below the toolbar island and above the page content.  Dismissible
via [×] — reappears on the next ``pipeline_status`` signal update.

Usage::

    banner = ProcessingBanner()
    banner.pipeline_status.connect(self._on_status)
    layout.insertWidget(1, banner)
"""

from __future__ import annotations

from PyQt6.QtGui import QColor  # noqa: F401 — used in commented-out progress styling
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

from moment.ui.resources import color

_BANNER_HEIGHT = 28


class ProcessingBanner(QWidget):
    """Pipeline status indicator with coloured text and a busy progress bar."""

    _STATUS_UPDATE_MS = 3000  # refresh interval (unused; kept for future polling)

    # Colour mapping per status
    _COLOR_MAP = {
        "encoding": "--accent-blue",
        "uploading": "--accent-green",
        "error": "--accent-red",
        "mixed": "--text-primary",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_BANNER_HEIGHT)
        self.setStyleSheet(f"""
            background-color: {color("--bg-surface")};
            border-bottom: 1px solid {color("--border-menu")};
        """)

        self._dismissed = False

        # Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        # Status text label
        self._label = QLabel("Idle")
        self._label.setStyleSheet(f"""
            color: {color("--text-primary")};
            font-size: 12px;
            font-weight: 500;
            border: none;
            background: transparent;
        """)
        layout.addWidget(self._label)

        # Indeterminate progress bar (busy indicator)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setFixedWidth(120)
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {color("--bg-inset")};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {color("--accent-blue")};
                border-radius: 2px;
            }}
        """)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        layout.addStretch()

        # Dismiss button
        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(18, 18)
        dismiss_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; color: #757575;
                font-size: 16px; font-weight: bold; padding: 0;
            }
            QPushButton:hover { color: #d9d9d9; }
        """)
        dismiss_btn.clicked.connect(self._on_dismiss)
        layout.addWidget(dismiss_btn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_status(self, status: str, count: int = 0, total: int = 0) -> None:
        """Set the banner text and colour from a pipeline status string.

        Args:
            status: One of ``"encoding"``, ``"uploading"``, ``"error"``,
                    ``"mixed"``, or ``"idle"``.
            count: Completed count (for progress text).
            total: Total count (for progress text).
        """
        self._dismissed = False
        self.setVisible(True)

        text_color = self._COLOR_MAP.get(status, "--text-primary")
        hex_color = color(text_color)

        if status in ("encoding", "uploading", "mixed"):
            verb = (
                "Encoding"
                if status == "encoding"
                else "Uploading"
                if status == "uploading"
                else "Processing"
            )
            self._label.setText(f"{verb} {count}/{total} clips…")
            style = (
                f"color: {hex_color};"
                " font-size: 12px;"
                " font-weight: 500;"
                " border: none; background: transparent;"
            )
            self._label.setStyleSheet(style)
            self._progress.setVisible(True)
        elif status == "error":
            self._label.setText("Pipeline error — check logs")
            style = (
                f"color: {hex_color};"
                " font-size: 12px;"
                " font-weight: 500;"
                " border: none; background: transparent;"
            )
            self._label.setStyleSheet(style)
            self._progress.setVisible(False)
        else:
            self._label.setText("Idle")
            style = (
                f"color: {color('--text-primary')};"
                " font-size: 12px;"
                " font-weight: 500;"
                " border: none; background: transparent;"
            )
            self._label.setStyleSheet(style)
            self._progress.setVisible(False)

    def _on_dismiss(self) -> None:
        """Hide the banner until next status update."""
        self._dismissed = True
        self.setVisible(False)
