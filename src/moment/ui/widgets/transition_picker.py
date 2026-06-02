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

from PyQt6.QtCore import (
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
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

        # Animation state for preview playback
        self._anim_progress = 1.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60fps
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_playing = False

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
                background-color: {color("--bg-inset")};
                border: 1px solid {color("--border-menu")};
                border-radius: 4px;
                padding: 2px;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-radius: 3px;
            }}
            QListWidget::item:selected {{
                background-color: {color("--accent-blue")};
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

    def closeEvent(self, event) -> None:
        """Stop animation timers on close to prevent teardown races."""
        self._anim_timer.stop()
        self._preview_timer.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_selection_changed(self, index: int) -> None:
        """Handle transition type selection change, playing preview animation."""
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

        # Play preview animation once
        self._start_anim()

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
    # Preview rendering — animated QPainter-based transition preview
    # -------------------------------------------------------------------

    def _start_anim(self) -> None:
        """Start a one-shot animation of the current transition."""
        self._anim_progress = 0.0
        self._anim_playing = True
        self._anim_timer.start()

    def _anim_tick(self) -> None:
        """Advance the preview animation by one frame."""
        step = 0.025  # ~40 frames for 1s animation
        self._anim_progress += step
        if self._anim_progress >= 1.0:
            self._anim_progress = 1.0
            self._anim_playing = False
            self._anim_timer.stop()
        self._render_preview()

    def _render_preview(self) -> None:
        """Render a visual preview of the selected transition.

        Draws two clip blocks (A and B) side by side with an animated
        transition effect: crossfade (alpha blend), slide (position),
        wipe (clipping path), or sharp cut (no animation).
        """
        size = 320
        pixmap = QPixmap(size, 120)
        pixmap.fill(QColor("#2a2a2a"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        mid = size // 2
        accent = QColor(color("--accent-blue"))

        progress = self._anim_progress
        key = self._selected.key

        if key == "cut":
            # Sharp cut — no animation, just show A then B
            draw_a = progress < 0.5
            self._draw_clip_block(painter, "Clip A", 0, 20, mid, 80, accent)
            if not draw_a:
                self._draw_clip_block(
                    painter, "Clip B", mid, 20, mid, 80, QColor(color("--accent-green"))
                )

        elif key in ("crossfade", "fade_black", "fade_white"):
            # Crossfade / fade — alpha blend between clips
            self._draw_clip_block(painter, "Clip A", 0, 20, mid, 80, accent, alpha=1.0 - progress)
            self._draw_clip_block(
                painter, "Clip B", mid, 20, mid, 80, QColor(color("--accent-green")), alpha=progress
            )
            # Fade overlay
            if key in ("fade_black", "fade_white"):
                fade_color = QColor(0, 0, 0) if "black" in key else QColor(255, 255, 255)
                fade_color.setAlpha(int(100 * abs(progress - 0.5) * 2))
                painter.fillRect(0, 20, size, 80, fade_color)

        elif key in ("whip_left", "whip_right"):
            # Whip — slide clips laterally
            direction = -1 if "left" in key else 1
            offset = int(size * progress * direction)
            self._draw_clip_block(painter, "Clip A", offset, 20, mid, 80, accent, alpha=0.7)
            self._draw_clip_block(
                painter,
                "Clip B",
                mid + offset,
                20,
                mid,
                80,
                QColor(color("--accent-green")),
                alpha=0.7,
            )
            # Motion blur lines
            blur_alpha = int(60 * (1.0 - progress))
            blur_color = QColor(accent)
            blur_color.setAlpha(blur_alpha)
            painter.setPen(QPen(blur_color, 2))
            for i in range(3):
                x = size // 2 + offset + (i - 1) * 15
                painter.drawLine(x, 30, x, 90)

        # Label
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(color("--text-secondary")))
        anim_tag = "" if self._anim_playing else " (done)"
        painter.drawText(
            QRect(0, 0, size, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"Preview: {self._selected.label}{anim_tag}",
        )
        painter.end()

        if self._preview_label is not None:
            self._preview_label.setPixmap(pixmap)

    @staticmethod
    def _draw_clip_block(
        painter: QPainter,
        label: str,
        x: int,
        y: int,
        w: int,
        h: int,
        border_color: QColor,
        *,
        alpha: float = 1.0,
    ) -> None:
        """Draw a single clip block with optional alpha."""
        fill = QColor("#3c3c3c")
        fill.setAlpha(int(200 * alpha))
        painter.fillRect(x, y, w, h, fill)

        bd = QColor(border_color)
        bd.setAlpha(int(255 * alpha))
        painter.setPen(QPen(bd, 1))
        painter.drawRect(x, y, w - 1, h - 1)

        txt = QColor("#d9d9d9")
        txt.setAlpha(int(255 * alpha))
        painter.setPen(QPen(txt, 1))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(
            QRect(x, y, w, h),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
