"""Trash page — soft-deleted clips with restore and permanent-delete options.

Uses the same QListView + ClipDelegate grid as GridPage.
Cards show deletion date instead of recording date in metadata.
Empty Trash action is in the main window toolbar.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListView,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from moment.ui.services.async_loader import AsyncDataLoader

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class TrashPage(QWidget):
    """Page displaying soft-deleted clips with restore / delete / empty-trash actions.

    Signals:
        clip_restored(str): Emitted with clip ID after restore.
        clips_removed: Emitted after a permanent delete or trash empty.
        empty_trash_requested: Emitted when user clicks Empty Trash (handled by main window).
    """

    clip_restored = pyqtSignal(str)
    clips_removed = pyqtSignal()

    def __init__(self, store: "Store | None" = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._clips: list[dict[str, Any]] = []

        # ── Model + delegate ────────────────────────────────────────────
        self._source_model = QStandardItemModel()

        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._delegate = ClipDelegate()

        # ── Grid view ───────────────────────────────────────────────────
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
        self._list_view.setSpacing(4)

        # ── Empty state ─────────────────────────────────────────────────
        self._empty_widget = self._build_empty_state()

        # ── Context menu (Restore / Delete Permanently) ─────────────────
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)

        # ── Layout ──────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(0)

        title = QLabel("Trash")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self._list_view, stretch=1)
        layout.addWidget(self._empty_widget, stretch=1)

        # Async loader
        self._loader: AsyncDataLoader | None = None

        # Start with empty state
        self._empty_widget.setVisible(True)
        self._list_view.setVisible(False)

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Reload all soft-deleted clips from the store asynchronously."""
        if self._store is None:
            self._show_empty("No database available.")
            return

        self._cancel_loader()

        self._loader = AsyncDataLoader(
            self._store.list_clips,
            include_deleted=True,
            limit=2000,
        )
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_load_error)
        self._loader.start()

    def empty_trash(self) -> None:
        """Triggered from main window toolbar — empty the trash."""
        self._on_empty_trash()

    def _on_data_ready(self, clips: list[Any]) -> None:
        self._loader = None
        deleted = [c for c in clips if c.deleted_at is not None]

        if not deleted:
            self._show_empty("Trash is empty")
            return

        self._empty_widget.setVisible(False)
        self._list_view.setVisible(True)
        self._populate(deleted)

    def _on_load_error(self, error: str) -> None:
        self._loader = None
        logger.exception("Failed to load trash clips: %s", error)
        self._show_empty(f"Could not load trash.\n{error}")

    def _cancel_loader(self) -> None:
        if self._loader is not None:
            self._loader.data_ready.disconnect()
            self._loader.error_occurred.disconnect()
            self._loader.cancel()
            self._loader = None

    def hideEvent(self, event) -> None:
        self._cancel_loader()
        super().hideEvent(event)

    def _populate(self, clips: list[Any]) -> None:
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._clips = []
        self._source_model.clear()

        for clip in clips:
            data = ClipDelegate.build_item_data(clip)
            # Override: show deletion date instead of recording date
            # ClipDelegate's paint reads "created_at" for the metadata row date
            if clip.deleted_at:
                if isinstance(clip.deleted_at, datetime):
                    data["deleted_at"] = clip.deleted_at.isoformat()
                    data["created_at"] = clip.deleted_at.isoformat()
                else:
                    data["deleted_at"] = str(clip.deleted_at)
                    data["created_at"] = str(clip.deleted_at)

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

    # ==================================================================
    # Actions
    # ==================================================================

    def _get_selected_ids(self) -> list[str]:
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return []
        ids: list[str] = []
        for idx in sel_model.selectedIndexes():
            data = idx.data(Qt.ItemDataRole.UserRole)
            if data and "id" in data:
                ids.append(data["id"])
        return list(set(ids))

    def _on_restore(self) -> None:
        selected = self._get_selected_ids()
        if not selected or self._store is None:
            return
        for clip_id in selected:
            try:
                self._store.restore_clip(clip_id)
                self.clip_restored.emit(clip_id)
            except Exception:
                logger.exception("Failed to restore clip %s", clip_id)
        self.refresh()

    def _on_permanent_delete(self) -> None:
        selected = self._get_selected_ids()
        if not selected or self._store is None:
            return
        reply = QMessageBox.question(
            self,
            "Permanently Delete",
            f"Permanently delete {len(selected)} clip(s)?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for clip_id in selected:
            try:
                self._store.delete_clip(clip_id, soft=False)
            except Exception:
                logger.exception("Failed to hard-delete clip %s", clip_id)
        self.clips_removed.emit()
        self.refresh()

    def _on_empty_trash(self) -> None:
        if self._store is None:
            return
        all_clips = self._store.list_clips(include_deleted=True, limit=2000)
        deleted = [c for c in all_clips if c.deleted_at is not None]
        if not deleted:
            return

        reply = QMessageBox.question(
            self,
            "Empty Trash",
            f"Permanently delete all {len(deleted)} clip(s) in Trash?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.empty_trash()
            self.clips_removed.emit()
            self.refresh()
        except Exception:
            logger.exception("Failed to empty trash")

    # ==================================================================
    # Context menu
    # ==================================================================

    def _on_context_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu

        selected = self._get_selected_ids()
        if not selected:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2a2a2a; border: 1px solid #3d3d3d;
                    color: var(--text-primary); }
            QMenu::item { padding: 6px 24px; }
            QMenu::item:selected { background-color: #323232; }
        """)

        restore = menu.addAction("Restore")
        delete = menu.addAction("Delete Permanently")
        menu.addSeparator()
        props = menu.addAction("Properties")

        action = menu.exec(self._list_view.viewport().mapToGlobal(pos))
        if action == restore:
            self._on_restore()
        elif action == delete:
            self._on_permanent_delete()
        elif action == props:
            pass  # Properties view — future enhancement

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
        icon = load_icon("empty-trash", "#555555")
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(64, 64))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        self._empty_label = QLabel("Trash is empty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "font-size: 16px; color: var(--text-secondary); background: transparent;"
        )
        layout.addWidget(self._empty_label)

        self._empty_cta = QLabel("")
        self._empty_cta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_cta.setStyleSheet(
            "font-size: 13px; color: var(--text-muted); background: transparent;"
        )
        layout.addWidget(self._empty_cta)

        return widget

    def _show_empty(self, message: str) -> None:
        self._list_view.setVisible(False)
        self._empty_label.setText(message)
        self._empty_widget.setVisible(True)
