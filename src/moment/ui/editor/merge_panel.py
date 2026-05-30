"""Merge panel — multi-clip merge timeline with transition picker.

Lets the user add clips from the grid, reorder them via drag handles,
choose per-gap transitions, and preview the merged output.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color
from moment.ui.widgets.transition_picker import TransitionPicker

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class MergePanel(QWidget):
    """Multi-clip merge timeline panel.

    Signals:
        profile_changed: Emitted when the merge configuration changes.
        preview_requested: Emitted with list of clip IDs to preview.
    """

    profile_changed = pyqtSignal()
    preview_requested = pyqtSignal(list)  # list[str]

    def __init__(self, store: "Store", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._clip_ids: list[str] = []
        self._transitions: list[dict[str, Any]] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def clip_ids(self) -> list[str]:
        return list(self._clip_ids)

    @property
    def transitions(self) -> list[dict[str, Any]]:
        return list(self._transitions)

    def add_clip(self, clip_id: str) -> None:
        """Add a clip to the end of the merge timeline."""
        if clip_id not in self._clip_ids:
            self._clip_ids.append(clip_id)
            self._refresh_list()
            self.profile_changed.emit()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # Instructions
        info = QLabel("Drag clips from the grid or use 'Add Clip' to compose a merged video.")
        info.setObjectName("cardMeta")
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Clip list ---
        self._list = QListWidget()
        self._list.setMinimumHeight(120)
        self._list.setStyleSheet(
            f"""
            QListWidget {{
                background-color: {color('--bg-inset')};
                border: 1px solid {color('--border-menu')};
                border-radius: 4px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-radius: 3px;
                margin: 1px 0;
                background-color: {color('--bg-surface')};
            }}
            QListWidget::item:selected {{
                background-color: {color('--accent-blue')};
                color: #ffffff;
            }}
            """
        )
        layout.addWidget(self._list)

        # --- Controls ---
        controls = QFrame()
        controls.setObjectName("toolbarIsland")
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(8, 6, 8, 6)
        ctrl_layout.setSpacing(6)

        add_btn = QPushButton("Add Clip…")
        add_btn.clicked.connect(self._on_add_clip)
        add_btn.setEnabled(False)
        add_btn.setToolTip("Drag clips from the grid to add them to the merge")
        ctrl_layout.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove_clip)
        ctrl_layout.addWidget(remove_btn)

        ctrl_layout.addStretch()

        move_up_btn = QPushButton("▲")
        move_up_btn.setFixedSize(32, 28)
        move_up_btn.clicked.connect(self._on_move_up)
        ctrl_layout.addWidget(move_up_btn)

        move_down_btn = QPushButton("▼")
        move_down_btn.setFixedSize(32, 28)
        move_down_btn.clicked.connect(self._on_move_down)
        ctrl_layout.addWidget(move_down_btn)

        layout.addWidget(controls)

        # --- Transition row ---
        trans_frame = QFrame()
        trans_frame.setObjectName("toolbarIsland")
        trans_layout = QHBoxLayout(trans_frame)
        trans_layout.setContentsMargins(8, 6, 8, 6)
        trans_layout.setSpacing(8)

        trans_layout.addWidget(QLabel("Transition between clips:"))
        self._trans_btn = QPushButton("Pick Transition…")
        self._trans_btn.clicked.connect(self._on_pick_transition)
        trans_layout.addWidget(self._trans_btn)

        self._trans_label = QLabel("Default: Cut")
        self._trans_label.setObjectName("cardMeta")
        trans_layout.addWidget(self._trans_label)

        trans_layout.addStretch()
        layout.addWidget(trans_frame)

        # --- Preview ---
        preview_btn = QPushButton("Preview Merge (first 3s)")
        preview_btn.setObjectName("accent")
        preview_btn.clicked.connect(self._on_preview)
        layout.addWidget(preview_btn)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        """Rebuild the list widget from current clip IDs."""
        self._list.clear()
        for cid in self._clip_ids:
            clip = self._store.get_clip(cid)
            label = clip.title if (clip and clip.title) else (clip.stem if clip else cid)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self._list.addItem(item)

    def _on_add_clip(self) -> None:
        """Stub — in practice, opens a clip picker dialog from the grid."""
        logger.debug("Add clip requested")

    def _on_remove_clip(self) -> None:
        """Remove the selected clip from the list."""
        current = self._list.currentRow()
        if 0 <= current < len(self._clip_ids):
            self._clip_ids.pop(current)
            self._refresh_list()
            self.profile_changed.emit()

    def _on_move_up(self) -> None:
        """Move the selected clip up in the order."""
        idx = self._list.currentRow()
        if idx > 0:
            self._clip_ids[idx], self._clip_ids[idx - 1] = \
                self._clip_ids[idx - 1], self._clip_ids[idx]
            self._refresh_list()
            self._list.setCurrentRow(idx - 1)
            self.profile_changed.emit()

    def _on_move_down(self) -> None:
        """Move the selected clip down in the order."""
        idx = self._list.currentRow()
        if 0 <= idx < len(self._clip_ids) - 1:
            self._clip_ids[idx], self._clip_ids[idx + 1] = \
                self._clip_ids[idx + 1], self._clip_ids[idx]
            self._refresh_list()
            self._list.setCurrentRow(idx + 1)
            self.profile_changed.emit()

    def _on_pick_transition(self) -> None:
        """Open the transition picker dialog."""
        dialog = TransitionPicker(parent=self)
        if dialog.exec() == TransitionPicker.DialogCode.Accepted:
            t = dialog.selected_transition()
            self._transitions.append(t)
            self._trans_label.setText(
                f"{t['type'].replace('_', ' ').title()} ({t['duration']}s)"
            )
            self.profile_changed.emit()

    def _on_preview(self) -> None:
        """Request a preview of the merged output."""
        if self._clip_ids:
            self.preview_requested.emit(list(self._clip_ids))
            self._trans_label.setText("Preview rendering…")
