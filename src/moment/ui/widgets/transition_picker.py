"""Transition picker dialog — select transitions between merged clips.

A modal QDialog that lets the user choose a transition type, duration, and
options for clip merging. Intended to be used alongside :class:`MergeDialog`.

Options:
- Cut (instant, default)
- Crossfade 0.5s / 1s / 2s
- Whip Left / Whip Right
- Fade to Black / Fade to White

Features:
- QListWidget with transition types
- Duration spinbox (for Crossfade only)
- "Preview transition" checkbox (renders preview in background thread)
- "Apply to all gaps" checkbox (for multi-clip merge)
- Returns a dict: ``{type: str, duration: float, params: dict}``

Usage::

    dialog = TransitionPicker(parent=self)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        transition = dialog.selected_transition()
        # transition = {"type": "crossfade", "duration": 1.0, "params": {}}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import Qt, QRect, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transition definitions
# ---------------------------------------------------------------------------


@dataclass
class _TransitionDef:
    """Internal descriptor for a transition option."""

    key: str
    label: str
    description: str
    has_duration: bool = False
    default_duration: float = 0.0
    min_duration: float = 0.0
    max_duration: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)


_TRANSITIONS: list[_TransitionDef] = [
    _TransitionDef("cut", "Cut", "Instant switch — no transition.", has_duration=False),
    _TransitionDef(
        "crossfade",
        "Crossfade",
        "Smooth dissolve between clips.",
        has_duration=True,
        default_duration=1.0,
        min_duration=0.5,
        max_duration=5.0,
        params={"xfade": "fade"},
    ),
    _TransitionDef(
        "whip_left",
        "Whip Left",
        "Fast pan whip to the left.",
        has_duration=False,
        default_duration=0.3,
        params={"whip": "left"},
    ),
    _TransitionDef(
        "whip_right",
        "Whip Right",
        "Fast pan whip to the right.",
        has_duration=False,
        default_duration=0.3,
        params={"whip": "right"},
    ),
    _TransitionDef(
        "fade_black",
        "Fade to Black",
        "Fade out to black, then fade in.",
        has_duration=True,
        default_duration=0.5,
        min_duration=0.25,
        max_duration=3.0,
        params={"fade": "black"},
    ),
    _TransitionDef(
        "fade_white",
        "Fade to White",
        "Fade out to white, then fade in.",
        has_duration=True,
        default_duration=0.5,
        min_duration=0.25,
        max_duration=3.0,
        params={"fade": "white"},
    ),
]


class TransitionPicker(QDialog):
    """Modal dialog for selecting a merge transition.

    Returns a dict via :meth:`selected_transition` with the shape::

        {"type": "crossfade", "duration": 1.0, "params": {"xfade": "fade"}}
    """

    # Emitted when the preview should be rendered (throttled)
    _preview_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transition Picker")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"background-color: {color('--bg-window')};")
        self.setModal(True)

        # State
        self._selected: _TransitionDef = _TRANSITIONS[0]
        self._duration = _TRANSITIONS[0].default_duration
        self._apply_all = False
        self._preview_enabled = False

        # Debounce preview requests
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._preview_requested.emit)

        # Connect preview signal to the render slot
        self._preview_requested.connect(self._render_preview)

        # Preview label (created here so _build_ui can reference it)
        self._preview_label: QLabel | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_transition(self) -> dict[str, Any]:
        """Return the selected transition as a dict.

        Returns:
            Dict with keys ``type``, ``duration``, ``params``, and
            ``apply_to_all``.
        """
        result: dict[str, Any] = {
            "type": self._selected.key,
            "duration": self._duration,
            "params": dict(self._selected.params),
            "apply_to_all": self._apply_all,
        }
        return result

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Choose Transition")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # Subtitle
        subtitle = QLabel("Select the transition effect applied between merged clips.")
        subtitle.setObjectName("cardMeta")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- Main content row ---
        content = QHBoxLayout()
        content.setSpacing(16)

        # Left: transition list
        left = QVBoxLayout()
        left.setSpacing(8)

        list_label = QLabel("Type")
        list_label.setObjectName("cardTitle")
        left.addWidget(list_label)

        self._list = QListWidget()
        self._list.setFixedHeight(180)
        self._list.setStyleSheet(
            f"""
            QListWidget {{
                background-color: {color('--bg-inset')};
                border: 1px solid {color('--border-menu')};
                border-radius: 4px;
                padding: 2px;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-radius: 3px;
            }}
            QListWidget::item:selected {{
                background-color: {color('--accent-blue')};
                color: #ffffff;
            }}
            """
        )
        for tdef in _TRANSITIONS:
            item = QListWidgetItem(tdef.label)
            item.setData(Qt.ItemDataRole.UserRole, tdef.key)
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        left.addWidget(self._list)

        content.addLayout(left)

        # Right: options panel
        right = QVBoxLayout()
        right.setSpacing(12)

        # Description label
        self._desc_label = QLabel(_TRANSITIONS[0].description)
        self._desc_label.setObjectName("cardMeta")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(f"color: {color('--text-secondary')}; font-size: 12px;")
        right.addWidget(self._desc_label)

        # Duration (shown only for transitions that support it)
        self._duration_widget = QWidget()
        dur_layout = QHBoxLayout(self._duration_widget)
        dur_layout.setContentsMargins(0, 0, 0, 0)
        dur_layout.setSpacing(8)

        dur_label = QLabel("Duration")
        dur_label.setObjectName("cardMeta")
        dur_layout.addWidget(dur_label)

        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setSuffix(" s")
        self._duration_spin.setDecimals(1)
        self._duration_spin.setRange(0.5, 5.0)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.setValue(1.0)
        self._duration_spin.valueChanged.connect(self._on_duration_changed)
        dur_layout.addWidget(self._duration_spin)

        dur_layout.addStretch()
        right.addWidget(self._duration_widget)

        self._update_duration_visibility()

        # Preview checkbox
        self._preview_check = QCheckBox("Preview transition")
        self._preview_check.setToolTip("Render a 2s preview between two thumbnails (uses ffmpeg)")
        self._preview_check.toggled.connect(self._on_preview_toggled)
        right.addWidget(self._preview_check)

        # Preview display label (shows rendered transition preview)
        self._preview_label = QLabel()
        self._preview_label.setFixedSize(320, 120)
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet(
            f"background-color: {color('--bg-inset')}; border-radius: 4px;"
        )
        self._preview_label.setVisible(self._preview_enabled)
        right.addWidget(self._preview_label)

        # Apply to all gaps checkbox
        self._apply_all_check = QCheckBox("Apply to all gaps")
        self._apply_all_check.setToolTip("Use this transition for every gap in a multi-clip merge")
        self._apply_all_check.toggled.connect(self._on_apply_all_toggled)
        right.addWidget(self._apply_all_check)

        right.addStretch()

        content.addLayout(right)
        layout.addLayout(content)

        # --- Bottom buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("accent")
        apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(apply_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_selection_changed(self, index: int) -> None:
        """Handle transition type selection change."""
        if index < 0 or index >= len(_TRANSITIONS):
            return

        tdef = _TRANSITIONS[index]
        self._selected = tdef
        self._duration = tdef.default_duration

        # Update description
        self._desc_label.setText(tdef.description)

        # Update duration control
        if tdef.has_duration:
            self._duration_spin.setRange(
                tdef.min_duration,
                tdef.max_duration,
            )
            self._duration_spin.setValue(tdef.default_duration)
        self._update_duration_visibility()

        # Request preview update (debounced)
        if self._preview_enabled:
            self._preview_timer.start()

    def _on_duration_changed(self, value: float) -> None:
        """Handle duration spinbox change."""
        self._duration = value

        if self._preview_enabled:
            self._preview_timer.start()

    def _on_preview_toggled(self, checked: bool) -> None:
        """Handle preview checkbox toggle."""
        self._preview_enabled = checked
        if self._preview_label is not None:
            self._preview_label.setVisible(checked)
        if checked:
            self._preview_timer.start()

    def _on_apply_all_toggled(self, checked: bool) -> None:
        """Handle 'apply to all gaps' toggle."""
        self._apply_all = checked

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_duration_visibility(self) -> None:
        """Show/hide duration controls based on selected transition."""
        self._duration_widget.setVisible(self._selected.has_duration)

    # ------------------------------------------------------------------
    # Preview rendering (stub — placeholder for ffmpeg overlay filter)
    # ------------------------------------------------------------------

    def _render_preview(self) -> None:
        """Render a 2s transition preview between two thumbnails.

        Currently shows a placeholder graphic that visualises the selected
        transition type.  Full ffmpeg overlay-filter rendering in a background
        thread will be implemented in a follow-up.
        """
        size = 320
        pixmap = QPixmap(size, 120)
        pixmap.fill(QColor("#2a2a2a"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        mid = size // 2
        accent = QColor(color("--accent-blue"))
        muted = QColor(color("--text-muted"))

        # Left "clip A" block
        painter.fillRect(0, 20, mid, 80, QColor("#3c3c3c"))
        painter.setPen(QPen(accent, 1))
        painter.drawRect(0, 20, mid - 1, 79)
        painter.setPen(QPen(muted, 1))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(QRect(0, 20, mid, 80), Qt.AlignmentFlag.AlignCenter, "Clip A")

        # Right "clip B" block
        painter.fillRect(mid, 20, mid, 80, QColor("#3c3c3c"))
        painter.setPen(QPen(QColor(color("--accent-green")), 1))
        painter.drawRect(mid, 20, mid - 1, 79)
        painter.drawText(QRect(mid, 20, mid, 80), Qt.AlignmentFlag.AlignCenter, "Clip B")

        # Transition indicator between the two blocks
        painter.setPen(QPen(accent, 2))
        painter.drawLine(mid, 20, mid, 100)

        # Arrows or effect-specific visual indicator around the transition line
        key = self._selected.key
        if key == "cut":
            pass  # sharp line is enough
        elif key in ("crossfade", "fade_black", "fade_white"):
            fade_alpha = QColor(color("--accent-blue"))
            fade_alpha.setAlpha(60)
            painter.fillRect(mid - 20, 20, 40, 80, fade_alpha)
        elif key in ("whip_left", "whip_right"):
            direction = "→" if "right" in key else "←"
            font.setPointSize(16)
            painter.setFont(font)
            painter.drawText(QRect(0, 0, size, 120), Qt.AlignmentFlag.AlignCenter, direction)

        # Label
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(color("--text-secondary")))
        painter.drawText(
            QRect(0, 0, size, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"Preview: {self._selected.label}",
        )
        painter.end()

        if self._preview_label is not None:
            self._preview_label.setPixmap(pixmap)
