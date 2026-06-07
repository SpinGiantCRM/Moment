"""Grid page — scrollable clip library with dynamic card sizing and rich empty state.

Uses a ``QListView`` in ``IconMode`` with a custom ``ClipDelegate`` painter.
Cards are lazy-loaded; only visible rows are rendered.  Supports
selection mode with batch operations (Tag, Favorite, Delete, etc.).

Toolbar interactions (search, sort, card-size) are handled by signals from
the main window's toolbar — this page exposes setter methods that the main
window connects.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import (
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDrag, QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.core.models import Clip
from moment.ui.services.async_loader import AsyncDataLoader
from moment.ui.widgets.context_menu import ContextMenuBuilder
from moment.ui.widgets.skeleton_card import SkeletonCard

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# Sort options
_SORT_OPTIONS = {
    "Newest": "-recorded_at",
    "Name A–Z": "title",
    "Name Z–A": "-title",
    "Longest": "-duration",
    "Shortest": "duration",
}

_BATCH_ACTIONS = ["Tag", "Favorite", "Delete", "Re-encode", "Re-upload", "Move to folder"]


class ClipFilterProxyModel(QSortFilterProxyModel):
    """Filters and sorts clips by title, game, and tags.

    Implements a dynamic sort via ``setSortColumnName`` / ``setSortDirection``
    that dispatches on the ``UserRole`` dict key in ``lessThan``.
    """

    _SORT_KEY_MAP: dict[str, str] = {
        "-recorded_at": "recorded_at",
        "recorded_at": "recorded_at",
        "-file_size": "file_size",
        "file_size": "file_size",
        "-duration": "duration",
        "duration": "duration",
        "title": "title",
        "-title": "title",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self._sort_column = "-recorded_at"

    def set_filter_text(self, text: str) -> None:
        self._filter_text = text.strip()
        self.invalidateFilter()

    def set_sort_column(self, sort_key: str) -> None:
        self._sort_column = sort_key
        order = (
            Qt.SortOrder.DescendingOrder
            if sort_key.startswith("-")
            else Qt.SortOrder.AscendingOrder
        )
        self.sort(0, order)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        if not left_data or not right_data:
            return False

        sort_key = self._SORT_KEY_MAP.get(self._sort_column, "created_at")
        descending = self._sort_column.startswith("-")

        left_val = left_data.get(sort_key, "")
        right_val = right_data.get(sort_key, "")

        if sort_key in ("file_size", "duration"):
            try:
                left_val = float(left_val)
                right_val = float(right_val)
            except (TypeError, ValueError):
                left_val = 0
                right_val = 0

        if isinstance(left_val, str) and isinstance(right_val, str):
            result = left_val.lower() < right_val.lower()
        else:
            try:
                result = left_val < right_val
            except TypeError:
                result = str(left_val) < str(right_val)

        return not result if descending else result

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._filter_text:
            return True
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        data = model.data(index, Qt.ItemDataRole.UserRole)
        if data is None:
            return False
        search = self._filter_text.lower()
        title = str(data.get("title", "") or "").lower()
        game = str(data.get("game", "") or "").lower()
        if search in title or search in game:
            return True
        tags = data.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if search in str(tag).lower():
                    return True
        return False


# Accepted video file extensions for drop-in
_DROP_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


class _DragDropListView(QListView):
    """QListView subclass that supports drag-out and drop-in."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        model = self.model()
        if model is None:
            return
        sel_model = self.selectionModel()
        if sel_model is None:
            return
        urls: list[QUrl] = []
        for idx in sel_model.selectedIndexes():
            source_idx = idx
            if isinstance(model, QSortFilterProxyModel):
                source_idx = model.mapToSource(idx)
            data = source_idx.data(Qt.ItemDataRole.UserRole)
            if data is None:
                continue
            enc = data.get("encoded_path", "")
            src = data.get("source_path", "")
            filepath = enc or src
            if filepath and Path(filepath).is_file():
                urls.append(QUrl.fromLocalFile(filepath))
        if not urls:
            return
        mime_data = QMimeData()
        mime_data.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(supportedActions)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in _DROP_VIDEO_EXTS and p.is_file():
                    paths.append(p)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


class GridPage(QWidget):
    """Grid page showing clip cards in a scrollable grid.

    Signals:
        clip_activated(str): Emitted with clip ID when a card is clicked.
        batch_action_requested(str, list[str]): Action name + clip IDs.
        selection_changed(int): Emitted with count of selected clips.
        files_dropped(list[Path]): Emitted when video files are dropped.
    """

    clip_activated = pyqtSignal(str)
    batch_action_requested = pyqtSignal(str, list)
    selection_changed = pyqtSignal(int)
    empty_action_requested = pyqtSignal(str)
    files_dropped = pyqtSignal(list)
    import_wizard_requested = pyqtSignal()

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._clips: list[dict[str, Any]] = []

        # Model
        self._source_model = QStandardItemModel()
        self._proxy_model = ClipFilterProxyModel()
        self._proxy_model.setSourceModel(self._source_model)
        self._proxy_model.setDynamicSortFilter(True)

        # Delegate
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._delegate = ClipDelegate()

        # ── Batch action bar ────────────────────────────────────────────
        self._batch_bar = QFrame()
        self._batch_bar.setObjectName("toolbarIsland")
        self._batch_bar.setVisible(False)
        batch_layout = QHBoxLayout(self._batch_bar)
        batch_layout.setContentsMargins(8, 4, 8, 4)
        batch_layout.setSpacing(4)

        self._batch_label = QLabel("0 selected")
        self._batch_label.setObjectName("cardMeta")
        batch_layout.addWidget(self._batch_label)
        batch_layout.addSpacing(8)

        for action in _BATCH_ACTIONS:
            btn = QPushButton(action)
            if action == "Delete":
                btn.setObjectName("danger")
            elif action in ("Tag", "Favorite", "Re-encode", "Re-upload"):
                btn.setObjectName("secondary")
            btn.clicked.connect(lambda checked, a=action: self._on_batch_action(a))
            batch_layout.addWidget(btn)

        self._invert_btn = QPushButton("Invert")
        self._invert_btn.setToolTip("Invert selection (Ctrl+Shift+I)")
        self._invert_btn.clicked.connect(self._invert_selection)
        batch_layout.addWidget(self._invert_btn)

        self._cancel_select_btn = QPushButton("Cancel")
        self._cancel_select_btn.clicked.connect(self._exit_selection_mode)
        batch_layout.addWidget(self._cancel_select_btn)

        # ── Async loader ────────────────────────────────────────────────
        self._loader: AsyncDataLoader | None = None

        # ── Skeleton cards ──────────────────────────────────────────────
        self._skeleton_cards: list[SkeletonCard] = []
        self._skeleton_container: QWidget | None = None

        # ── Grid view ───────────────────────────────────────────────────
        self._list_view = _DragDropListView()
        self._list_view.setViewMode(QListView.ViewMode.IconMode)
        self._list_view.setGridSize(QSize(284, 192))  # medium default
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setMovement(QListView.Movement.Static)
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setModel(self._proxy_model)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setLayoutMode(QListView.LayoutMode.Batched)
        self._list_view.setBatchSize(50)
        self._list_view.setWrapping(True)
        self._list_view.setWordWrap(True)
        self._list_view.setSpacing(4)

        self._list_view.clicked.connect(self._on_item_clicked)
        if self._list_view.selectionModel():
            self._list_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._list_view.files_dropped.connect(self.files_dropped.emit)

        # Register for skeleton shimmer repaints
        ClipDelegate.register_shimmer_view(self._list_view)

        # ── Empty / error states ────────────────────────────────────────
        self._empty_widget = self._build_empty_state()
        self._error_widget = self._build_error_state()

        # ── Layout ──────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._batch_bar)
        layout.addWidget(self._list_view, stretch=1)
        layout.addWidget(self._empty_widget, stretch=1)
        layout.addWidget(self._error_widget, stretch=1)

        self._empty_widget.setVisible(True)
        self._list_view.setVisible(False)
        self._error_widget.setVisible(False)

        # ── Shortcuts ───────────────────────────────────────────────────
        self._invert_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self._invert_shortcut.activated.connect(self._invert_selection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ==================================================================
    # Tools menu
    # ==================================================================

    def create_tools_menu(self) -> QMenu:
        """Build the Tools menu (Import recordings…)."""
        menu = QMenu(self)
        import_action = menu.addAction("Import recordings…")
        import_action.triggered.connect(self.import_wizard_requested.emit)
        return menu

    # ==================================================================
    # Public API — called from main window toolbar signals
    # ==================================================================

    def set_search_text(self, text: str) -> None:
        """Apply search filter from the main toolbar."""
        self._proxy_model.set_filter_text(text)
        self._update_empty_if_needed()

    def set_sort(self, sort_text: str) -> None:
        """Apply sort from the main toolbar dropdown."""
        sort_col = _SORT_OPTIONS.get(sort_text, "-recorded_at")
        self._proxy_model.set_sort_column(sort_col)

    def set_card_size(self, size: int) -> None:
        """Apply card size from the main toolbar toggle (0=small, 1=medium, 2=large)."""
        from moment.ui.widgets.clip_delegate import _CARD_SIZES as _CARD_LAYOUTS
        from moment.ui.widgets.clip_delegate import ClipDelegate

        size = max(0, min(2, size))
        ClipDelegate.set_card_size(size)

        lo = _CARD_LAYOUTS.get(size, _CARD_LAYOUTS[1])
        card_w = lo["card_w"]
        card_h = lo["card_h"]
        self._list_view.setGridSize(QSize(card_w + 12, card_h + 16))
        self._list_view.scheduleDelayedItemsLayout()

    # ==================================================================
    # Load / refresh
    # ==================================================================

    def refresh(self) -> None:
        """Reload all clips from the store asynchronously."""
        if self._store is None:
            self._show_empty("No database available.\nStart Moment with a valid store.")
            return
        self._cancel_loader()
        self._show_skeletons(8)
        self._loader = AsyncDataLoader(
            self._store.list_clips,
            include_deleted=False,
            limit=2000,
        )
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_load_error)
        self._loader.start()

    def _on_data_ready(self, clips: list[Any]) -> None:
        self._loader = None
        self._remove_skeletons()
        if not clips:
            self._show_empty(
                "Press F8 in-game to capture clips, or use Import recordings below."
            )
            return
        self._hide_states()
        self._list_view.setVisible(True)
        self._populate(clips)
        logger.debug("Grid refreshed: %d clips", len(clips))

    def _on_load_error(self, error: str) -> None:
        self._loader = None
        self._remove_skeletons()
        logger.exception("Failed to load clips: %s", error)
        self._show_error(f"Could not load clips. Database error.\n\n{error}")

    def _populate(self, clips: list[Any]) -> None:
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._clips = []
        self._source_model.clear()

        for clip in clips:
            data = ClipDelegate.build_item_data(clip)
            self._clips.append(data)
            item = QStandardItem()
            item.setData(data, Qt.ItemDataRole.UserRole)
            delegate = self._delegate
            if delegate is not None:
                item.setSizeHint(delegate.sizeHint(None, self._source_model.index(0, 0)))
            else:
                item.setSizeHint(QSize(272, 176))
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemNeverHasChildren
            )
            a11y = data.get("accessible_description", "")
            if a11y:
                item.setData(a11y, Qt.ItemDataRole.AccessibleDescriptionRole)
            self._source_model.appendRow(item)

    def _update_empty_if_needed(self) -> None:
        """Show empty state if the filtered list is empty."""
        if self._proxy_model.rowCount() == 0 and self._source_model.rowCount() > 0:
            self._show_empty("Try different search terms", is_search_empty=True)
        elif self._proxy_model.rowCount() > 0:
            self._list_view.setVisible(True)
            if self._empty_widget:
                self._empty_widget.setVisible(False)

    # ==================================================================
    # Selection / batch
    # ==================================================================

    def _on_item_clicked(self, index: QModelIndex) -> None:
        source_index = self._proxy_model.mapToSource(index)
        data = source_index.data(Qt.ItemDataRole.UserRole)
        if data and "id" in data:
            self.clip_activated.emit(data["id"])

    def _cancel_loader(self) -> None:
        if self._loader is not None:
            self._loader.data_ready.disconnect()
            self._loader.error_occurred.disconnect()
            self._loader.cancel()
            self._loader = None

    def hideEvent(self, event) -> None:
        self._cancel_loader()
        super().hideEvent(event)

    def _on_selection_changed(self) -> None:
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return
        selected = sel_model.selectedIndexes()
        count = len(set(idx.row() for idx in selected))
        if count > 0:
            self._batch_bar.setVisible(True)
            self._batch_label.setText(f"{count} selected")
        else:
            self._batch_bar.setVisible(False)
        self.selection_changed.emit(count)

    def _on_batch_action(self, action: str) -> None:
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return
        selected_ids: list[str] = []
        for idx in sel_model.selectedIndexes():
            source_idx = self._proxy_model.mapToSource(idx)
            data = source_idx.data(Qt.ItemDataRole.UserRole)
            if data and "id" in data:
                selected_ids.append(data["id"])
        if selected_ids:
            self.batch_action_requested.emit(action, selected_ids)
            logger.info("Batch %s on %d clips", action, len(selected_ids))

    def _exit_selection_mode(self) -> None:
        self._list_view.clearSelection()
        self._batch_bar.setVisible(False)

    def enter_selection_mode(self) -> None:
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

    def _invert_selection(self) -> None:
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return
        row_count = self._proxy_model.rowCount()
        if row_count == 0:
            return
        sel_model.blockSignals(True)
        try:
            for row in range(row_count):
                idx = self._proxy_model.index(row, 0)
                sel_model.select(
                    idx,
                    QItemSelectionModel.SelectionFlag.Toggle
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        finally:
            sel_model.blockSignals(False)
        self._on_selection_changed()

    # ==================================================================
    # Empty / error states
    # ==================================================================

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        # Icon
        from moment.ui.resources import load_icon

        icon_label = QLabel()
        icon = load_icon("empty-library", "#6b6b6b")
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Heading
        self._empty_heading = QLabel("No clips yet")
        self._empty_heading.setObjectName("emptyStateHeading")
        self._empty_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_heading)

        # Description
        self._empty_desc = QLabel(
            "Press F8 in-game to capture clips, or import existing recordings"
        )
        self._empty_desc.setObjectName("emptyStateDesc")
        self._empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_desc.setWordWrap(True)
        layout.addWidget(self._empty_desc)

        # CTA buttons
        cta_layout = QHBoxLayout()
        cta_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        record_btn = QPushButton("Record a clip")
        record_btn.setObjectName("primary")
        record_btn.clicked.connect(lambda: self.empty_action_requested.emit("Start Recording"))
        cta_layout.addWidget(record_btn)
        import_btn = QPushButton("Import recordings")
        import_btn.setObjectName("secondary")
        import_btn.clicked.connect(
            lambda: self.empty_action_requested.emit("Import Recordings")
        )
        cta_layout.addWidget(import_btn)
        layout.addLayout(cta_layout)

        widget.setVisible(False)
        return widget

    def _build_error_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = QLabel("!")
        from moment.ui.resources import color as theme_color

        icon.setStyleSheet(
            f"font-size: 48px; color: {theme_color('--accent-red')}; background: transparent;"
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self._error_label = QLabel()
        self._error_label.setObjectName("emptyStateDesc")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reset_btn = QPushButton("Reset Database")
        reset_btn.setObjectName("danger")
        reset_btn.clicked.connect(lambda: self.empty_action_requested.emit("Reset Database"))
        btn_layout.addWidget(reset_btn)
        config_btn = QPushButton("Open Config Folder")
        config_btn.clicked.connect(lambda: self.empty_action_requested.emit("Open Config Folder"))
        btn_layout.addWidget(config_btn)
        layout.addLayout(btn_layout)

        widget.setVisible(False)
        return widget

    def _hide_states(self) -> None:
        if self._empty_widget:
            self._empty_widget.setVisible(False)
        if self._error_widget:
            self._error_widget.setVisible(False)

    def _show_empty(self, message: str, is_search_empty: bool = False) -> None:
        self._list_view.setVisible(False)
        self._batch_bar.setVisible(False)
        if self._error_widget:
            self._error_widget.setVisible(False)
        if is_search_empty:
            self._empty_heading.setText("No results found")
        else:
            self._empty_heading.setText("No clips yet")
        self._empty_desc.setText(message)
        if self._empty_widget:
            self._empty_widget.setVisible(True)

    def _show_error(self, message: str) -> None:
        self._list_view.setVisible(False)
        self._batch_bar.setVisible(False)
        if self._empty_widget:
            self._empty_widget.setVisible(False)
        self._error_label.setText(message)
        if self._error_widget:
            self._error_widget.setVisible(True)

    # ==================================================================
    # Skeleton cards
    # ==================================================================

    def _show_skeletons(self, count: int = 8) -> None:
        self._remove_skeletons()
        self._hide_states()
        self._list_view.setVisible(False)
        self._skeleton_container = QWidget(self)
        layout = QHBoxLayout(self._skeleton_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addStretch()
        for _ in range(min(count, 12)):
            card = SkeletonCard(self._skeleton_container)
            self._skeleton_cards.append(card)
            layout.addWidget(card)
            layout.addStretch()
        parent_layout = self.layout()
        if parent_layout is not None:
            list_idx = parent_layout.indexOf(self._list_view)
            if list_idx >= 0:
                parent_layout.insertWidget(list_idx, self._skeleton_container)
        self._skeleton_container.setVisible(True)

    def _remove_skeletons(self) -> None:
        for card in self._skeleton_cards:
            card.deleteLater()
        self._skeleton_cards.clear()
        if self._skeleton_container is not None:
            self._skeleton_container.deleteLater()
            self._skeleton_container = None

    # ==================================================================
    # Keyboard / context menu
    # ==================================================================

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_A:
                self._list_view.selectAll()
            elif key == Qt.Key.Key_B:
                self.enter_selection_mode()
            return
        if key == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        index = self._list_view.indexAt(event.pos())
        if not index.isValid():
            return
        source_idx = self._proxy_model.mapToSource(index)
        data = source_idx.data(Qt.ItemDataRole.UserRole)
        if not data or "id" not in data:
            return
        clip = Clip(
            id=data["id"],
            stem=data.get("stem", ""),
            source_path=Path(data.get("source_path", "")),
            encoded_path=Path(data["encoded_path"]) if data.get("encoded_path") else None,
            r2_url=data.get("r2_url") or None,
            favorite=data.get("favorite", False),
            protect_from_retention=data.get("protect_from_retention", False),
        )
        builder = ContextMenuBuilder(clip, self)
        builder.copy_url_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Copy URL", [cid])
        )
        builder.rename_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Rename", [cid])
        )
        builder.open_source_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Open Source", [cid])
        )
        builder.open_encoded_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Open Encoded", [cid])
        )
        builder.open_player_triggered.connect(self.clip_activated.emit)
        builder.reencode_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Re-encode", [cid])
        )
        builder.reupload_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Re-upload", [cid])
        )
        builder.favorite_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Favorite", [cid])
        )
        builder.manage_tags_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Tag", [cid])
        )
        builder.set_game_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Set Game", [cid])
        )
        builder.protect_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Protect", [cid])
        )
        builder.delete_triggered.connect(
            lambda cid: self.batch_action_requested.emit("Delete", [cid])
        )
        builder.select_triggered.connect(lambda cid: self.enter_selection_mode())
        menu = builder.build()
        menu.exec(event.globalPos())
