"""Trash page — soft-deleted clips with restore and permanent-delete options.

Reuses the same ``QListView`` + ``ClipDelegate`` grid pattern as ``GridPage``.
Each card shows a ``deleted_at`` overlay instead of a status badge.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class TrashPage(QWidget):
    """Page displaying soft-deleted clips with restore / delete / empty-trash actions.

    Signals:
        clip_restored(str): Emitted with clip ID after restore.
        clips_removed: Emitted after a permanent delete or trash empty.
    """

    clip_restored = pyqtSignal(str)
    clips_removed = pyqtSignal()

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._clips: list[dict[str, Any]] = []

        # --- Model ---
        self._source_model = QStandardItemModel()

        # --- Delegate ---
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._delegate = ClipDelegate()

        # --- Actions bar ---
        actions_bar = QFrame()
        actions_bar.setObjectName("toolbarIsland")
        actions_layout = QHBoxLayout(actions_bar)
        actions_layout.setContentsMargins(8, 4, 8, 4)
        actions_layout.setSpacing(8)

        self._restore_btn = QPushButton("Restore Selected")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.setEnabled(False)
        actions_layout.addWidget(self._restore_btn)

        self._delete_btn = QPushButton("Permanently Delete")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.clicked.connect(self._on_permanent_delete)
        self._delete_btn.setEnabled(False)
        actions_layout.addWidget(self._delete_btn)

        actions_layout.addStretch()

        self._empty_btn = QPushButton("Empty Trash")
        self._empty_btn.setObjectName("danger")
        self._empty_btn.clicked.connect(self._on_empty_trash)
        actions_layout.addWidget(self._empty_btn)

        # --- Grid view ---
        self._list_view = QListView()
        self._list_view.setViewMode(QListView.ViewMode.IconMode)
        self._list_view.setIconSize(QSize(260, 190))
        self._list_view.setGridSize(QSize(272, 206))
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setMovement(QListView.Movement.Static)
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setModel(self._source_model)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setLayoutMode(QListView.LayoutMode.Batched)
        self._list_view.setBatchSize(50)
        self._list_view.setWrapping(True)
        self._list_view.setWordWrap(True)
        self._list_view.setSpacing(4)

        sel_model = self._list_view.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)

        # --- Empty state ---
        self._empty_widget = self._build_empty_state()

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Trash")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(actions_bar)
        layout.addLayout(title_row)
        layout.addWidget(self._list_view, stretch=1)
        layout.addWidget(self._empty_widget, stretch=1)

        # Start with empty state
        self._empty_widget.setVisible(True)
        self._list_view.setVisible(False)

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Reload all soft-deleted clips from the store."""
        if self._store is None:
            self._show_empty("No database available.")
            return

        try:
            clips = self._store.list_clips(include_deleted=True, limit=2000)
            deleted = [c for c in clips if c.deleted_at is not None]

            if not deleted:
                self._show_empty("Trash is empty")
                return

            self._empty_widget.setVisible(False)
            self._list_view.setVisible(True)

            self._populate(deleted)
            logger.debug("Trash refreshed: %d deleted clips", len(deleted))
        except Exception as exc:
            logger.exception("Failed to load trash clips")
            self._show_empty(f"Could not load trash: {exc}")

    def _populate(self, clips: list[Any]) -> None:
        """Populate the grid with soft-deleted clips."""
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._clips = []
        self._source_model.clear()

        for clip in clips:
            data = ClipDelegate.build_item_data(clip)
            # Add deleted_at info for the overlay
            if clip.deleted_at:
                data["deleted_at"] = clip.deleted_at.isoformat() if isinstance(clip.deleted_at, datetime) else str(clip.deleted_at)
            self._clips.append(data)

            item = QStandardItem()
            item.setData(data, Qt.ItemDataRole.UserRole)
            item.setSizeHint(QSize(260, 190))
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemNeverHasChildren
            )
            self._source_model.appendRow(item)

        self._update_button_states()

    # ==================================================================
    # Actions
    # ==================================================================

    def _on_restore(self) -> None:
        """Restore selected clips."""
        selected = self._get_selected_ids()
        if not selected or self._store is None:
            return

        count = 0
        for clip_id in selected:
            try:
                self._store.restore_clip(clip_id)
                count += 1
                self.clip_restored.emit(clip_id)
            except Exception:
                logger.exception("Failed to restore clip %s", clip_id)

        if count > 0:
            self.refresh()
            logger.info("Restored %d clips", count)

    def _on_permanent_delete(self) -> None:
        """Permanently delete selected clips after confirmation."""
        selected = self._get_selected_ids()
        if not selected or self._store is None:
            return

        reply = QMessageBox.question(
            self, "Permanently Delete",
            f"Permanently delete {len(selected)} clip(s)?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        count = 0
        for clip_id in selected:
            try:
                self._store.delete_clip(clip_id, soft=False)
                count += 1
            except Exception:
                logger.exception("Failed to hard-delete clip %s", clip_id)

        if count > 0:
            self.clips_removed.emit()
            self.refresh()
            logger.info("Permanently deleted %d clips", count)

    def _on_empty_trash(self) -> None:
        """Empty the entire trash after confirmation."""
        if self._store is None:
            return

        # Count deleted clips
        all_clips = self._store.list_clips(include_deleted=True, limit=2000)
        deleted = [c for c in all_clips if c.deleted_at is not None]
        if not deleted:
            return

        total = len(deleted)

        reply = QMessageBox.question(
            self, "Empty Trash",
            f"Permanently delete all {total} clip(s) in Trash?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = self._store.empty_trash()
            self.clips_removed.emit()
            self.refresh()
            logger.info("Emptied trash: %d clips removed", removed)
        except Exception:
            logger.exception("Failed to empty trash")

    # ==================================================================
    # Helpers
    # ==================================================================

    def _get_selected_ids(self) -> list[str]:
        """Return list of clip IDs for all selected items."""
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return []

        ids: list[str] = []
        for idx in sel_model.selectedIndexes():
            data = idx.data(Qt.ItemDataRole.UserRole)
            if data and "id" in data:
                ids.append(data["id"])
        return list(set(ids))

    def _on_selection_changed(self) -> None:
        """Enable/disable action buttons based on selection."""
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update button enabled states based on current selection."""
        sel_model = self._list_view.selectionModel()
        has_selection = sel_model is not None and len(sel_model.selectedIndexes()) > 0
        self._restore_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    # ==================================================================
    # Empty state
    # ==================================================================

    def _build_empty_state(self) -> QWidget:
        """Build the centered empty-state widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🗑")
        icon.setObjectName("pageTitle")
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self._empty_label = QLabel("Trash is empty")
        self._empty_label.setObjectName("muted")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        widget.setVisible(False)
        return widget

    def _show_empty(self, message: str) -> None:
        """Display the empty state."""
        self._list_view.setVisible(False)
        self._restore_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

        self._empty_label.setText(message)
        self._empty_widget.setVisible(True)
