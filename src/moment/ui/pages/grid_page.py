"""Grid page — scrollable clip library with search, sort, and batch operations.

Uses a ``QListView`` in ``IconMode`` with a custom ``ClipDelegate`` painter.
Cards are lazy-loaded; only visible rows are rendered.  Supports
selection mode with batch operations (Tag, Favorite, Delete, etc.).
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
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDrag, QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
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
    "Newest first": "-recorded_at",
    "Oldest first": "recorded_at",
    "Largest file": "-file_size",
    "Smallest file": "file_size",
    "Longest": "-duration",
    "Shortest": "duration",
    "A–Z": "title",
    "Z–A": "-title",
}

_BATCH_ACTIONS = ["Tag", "Favorite", "Delete", "Re-encode", "Re-upload", "Move to folder"]


class ClipFilterProxyModel(QSortFilterProxyModel):
    """Filters and sorts clips by title, game, and tags.

    Implements a dynamic sort via ``setSortColumnName`` / ``setSortDirection``
    that dispatches on the ``UserRole`` dict key in ``lessThan``.
    """

    # Map sort option strings to dict keys
    _SORT_KEY_MAP: dict[str, str] = {
        "-recorded_at": "created_at",
        "recorded_at": "created_at",
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
        """Set the search text and invalidate the filter."""
        self._filter_text = text.strip()
        self.invalidateFilter()

    def set_sort_column(self, sort_key: str) -> None:
        """Set the sort column (e.g. ``"-recorded_at"``) and refresh."""
        self._sort_column = sort_key
        order = (
            Qt.SortOrder.DescendingOrder
            if sort_key.startswith("-")
            else Qt.SortOrder.AscendingOrder
        )
        self.sort(0, order)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Compare two items by the current sort key."""
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)

        if not left_data or not right_data:
            return False

        sort_key = self._SORT_KEY_MAP.get(self._sort_column, "created_at")
        descending = self._sort_column.startswith("-")

        left_val = left_data.get(sort_key, "")
        right_val = right_data.get(sort_key, "")

        # Numeric comparison for file_size, duration
        if sort_key in ("file_size", "duration"):
            try:
                left_val = float(left_val)
                right_val = float(right_val)
            except (TypeError, ValueError):
                left_val = 0
                right_val = 0

        # String comparison for title, created_at
        if isinstance(left_val, str) and isinstance(right_val, str):
            result = left_val.lower() < right_val.lower()
        else:
            try:
                result = left_val < right_val
            except TypeError:
                result = str(left_val) < str(right_val)

        return not result if descending else result

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """Accept rows that match the filter text in title, game, or tags."""
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

        # Also search tags if present
        tags = data.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if search in str(tag).lower():
                    return True

        return False


# Accepted video file extensions for drop-in
_DROP_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


class _DragDropListView(QListView):
    """QListView subclass that supports drag-out (clip → file manager)
    and drop-in (file manager → grid import).

    Signals:
        files_dropped(list[Path]): Emitted when video files are dropped.
    """

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    # ------------------------------------------------------------------
    # Drag-out: clip → file manager
    # ------------------------------------------------------------------

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        """Initiate a drag operation with file URLs for selected clips."""
        model = self.model()
        if model is None:
            return

        sel_model = self.selectionModel()
        if sel_model is None:
            return

        # Collect file paths from selected items
        urls: list[QUrl] = []
        for idx in sel_model.selectedIndexes():
            # Map through proxy model if needed
            source_idx = idx
            if isinstance(model, QSortFilterProxyModel):
                source_idx = model.mapToSource(idx)
            data = source_idx.data(Qt.ItemDataRole.UserRole)
            if data is None:
                continue

            # Prefer encoded path (MP4), fall back to source path (MKV)
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

    # ------------------------------------------------------------------
    # Drop-in: file manager → grid import
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        """Accept drops containing file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        """Accept drag-move with file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        """Handle dropped files — validate and emit paths."""
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
        files_dropped(list[Path]): Emitted when video files are dropped onto the grid.
    """

    clip_activated = pyqtSignal(str)
    batch_action_requested = pyqtSignal(str, list)
    selection_changed = pyqtSignal(int)
    empty_action_requested = pyqtSignal(str)
    files_dropped = pyqtSignal(list)

    # Cards per row for dynamic sizing
    CARDS_PER_ROW = 4

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

        # --- Search bar ---
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter clips…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setMinimumWidth(300)

        # Debounced search (300ms)
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)
        self._search_input.textChanged.connect(self._on_search_text_changed)

        # --- Sort dropdown ---
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(list(_SORT_OPTIONS.keys()))
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)

        # --- Refresh button ---
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Refresh clip list")
        self._refresh_btn.clicked.connect(self.refresh)
        self._refresh_btn.setFixedSize(28, 28)

        # --- Toolbar island ---
        toolbar = QFrame()
        toolbar.setObjectName("toolbarIsland")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(8)
        toolbar_layout.addWidget(self._search_input)
        toolbar_layout.addWidget(self._sort_combo)
        toolbar_layout.addWidget(self._refresh_btn)

        # --- Batch action bar (hidden by default) ---
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
            btn.clicked.connect(lambda checked, a=action: self._on_batch_action(a))
            batch_layout.addWidget(btn)

        self._invert_btn = QPushButton("Invert")
        self._invert_btn.setToolTip("Invert selection (Ctrl+Shift+I)")
        self._invert_btn.clicked.connect(self._invert_selection)
        batch_layout.addWidget(self._invert_btn)

        self._cancel_select_btn = QPushButton("Cancel")
        self._cancel_select_btn.clicked.connect(self._exit_selection_mode)
        batch_layout.addWidget(self._cancel_select_btn)

        self._loader: AsyncDataLoader | None = None

        # Skeleton cards for async loading
        self._skeleton_cards: list[SkeletonCard] = []
        self._skeleton_container: QWidget | None = None

        # --- Grid view (drag-and-drop enabled) ---
        self._list_view = _DragDropListView()
        self._list_view.setViewMode(QListView.ViewMode.IconMode)
        self._list_view.setIconSize(QSize(272, 176))
        self._list_view.setGridSize(QSize(284, 192))
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
        self._list_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._list_view.files_dropped.connect(self.files_dropped.emit)

        # --- Empty / error states ---
        self._empty_widget = self._build_empty_state()
        self._error_widget = self._build_error_state()
        self._state_stack: QWidget | None = None

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        # Title row (search + sort toolbar moved to main window ONLYOFFICE-style panel)
        # The toolbar_island is kept but hidden — the main window now provides
        # a shared top toolbar panel with search, sort, and page actions.
        toolbar_row = QHBoxLayout()
        toolbar.setVisible(False)  # Hidden: now in main window toolbar panel
        toolbar_row.addWidget(toolbar)
        toolbar_row.addStretch()
        layout.addLayout(toolbar_row)

        layout.addWidget(self._batch_bar)
        layout.addWidget(self._list_view, stretch=1)
        layout.addWidget(self._empty_widget, stretch=1)
        layout.addWidget(self._error_widget, stretch=1)

        # Start with empty state visible, grid hidden
        self._empty_widget.setVisible(True)
        self._list_view.setVisible(False)
        self._error_widget.setVisible(False)

        # --- Invert selection shortcut (Ctrl+Shift+I) ---
        self._invert_shortcut = QShortcut(QKeySequence("Ctrl+Shift+I"), self)
        self._invert_shortcut.activated.connect(self._invert_selection)

        # --- Shortcuts ---
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Reload all clips from the store asynchronously.

        Shows skeleton cards immediately, cancels any in-flight loader,
        then loads data on a background thread.
        """
        if self._store is None:
            self._show_empty("No database available.\nStart Moment with a valid store.")
            return

        # Cancel any previous loader (also disconnects signals)
        self._cancel_loader()

        # Show skeleton placeholders immediately
        self._show_skeletons(8)

        # Fire async load
        self._loader = AsyncDataLoader(
            self._store.list_clips, include_deleted=False, limit=2000
        )
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_load_error)
        self._loader.start()

    def _on_data_ready(self, clips: list[Any]) -> None:
        """Handle successful async clip load."""
        self._loader = None
        self._remove_skeletons()

        if not clips:
            self._show_empty(
                "No clips yet\n\nPress F8 in-game to capture your first clip."
            )
            return

        self._hide_states()
        self._list_view.setVisible(True)
        self._populate(clips)
        logger.debug("Grid refreshed: %d clips", len(clips))

    def _on_load_error(self, error: str) -> None:
        """Handle async load failure."""
        self._loader = None
        self._remove_skeletons()
        logger.exception("Failed to load clips: %s", error)
        self._show_error(f"Could not load clips. Database error.\n\n{error}")

    def _populate(self, clips: list[Any]) -> None:
        """Populate the model with clip data."""
        from moment.ui.widgets.clip_delegate import ClipDelegate

        self._clips = []
        self._source_model.clear()

        for clip in clips:
            data = ClipDelegate.build_item_data(clip)
            self._clips.append(data)

            item = QStandardItem()
            item.setData(data, Qt.ItemDataRole.UserRole)
            item.setSizeHint(QSize(272, 176))
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemNeverHasChildren
            )
            # Accessible description for screen readers (set once at creation)
            a11y = data.get("accessible_description", "")
            if a11y:
                item.setData(a11y, Qt.ItemDataRole.AccessibleDescriptionRole)
            self._source_model.appendRow(item)

    # ==================================================================
    # Filter / sort
    # ==================================================================

    def _on_search_text_changed(self, text: str) -> None:
        """Debounced search text handler."""
        self._search_timer.start()

    def _apply_filter(self) -> None:
        """Apply the current search text to the proxy model."""
        self._proxy_model.set_filter_text(self._search_input.text())
        self._update_empty_if_needed()

    def _on_sort_changed(self, text: str) -> None:
        """Update the sort order from the dropdown."""
        sort_col = _SORT_OPTIONS.get(text, "-recorded_at")
        self._proxy_model.set_sort_column(sort_col)

    def _update_empty_if_needed(self) -> None:
        """Show empty state if the filtered list is empty."""
        if self._proxy_model.rowCount() == 0 and self._source_model.rowCount() > 0:
            self._show_empty("No clips match your search.")
        elif self._proxy_model.rowCount() > 0:
            self._list_view.setVisible(True)
            if self._empty_widget:
                self._empty_widget.setVisible(False)

    # ==================================================================
    # Selection / batch
    # ==================================================================

    def _on_item_clicked(self, index: QModelIndex) -> None:
        """Handle single-click on a clip card."""
        source_index = self._proxy_model.mapToSource(index)
        data = source_index.data(Qt.ItemDataRole.UserRole)
        if data and "id" in data:
            self.clip_activated.emit(data["id"])

    def _cancel_loader(self) -> None:
        """Cancel and disconnect any in-flight async loader."""
        if self._loader is not None:
            self._loader.data_ready.disconnect()
            self._loader.error_occurred.disconnect()
            self._loader.cancel()
            self._loader = None

    def hideEvent(self, event) -> None:
        """Cancel in-flight loaders when the page is hidden."""
        self._cancel_loader()
        super().hideEvent(event)

    def _on_selection_changed(self) -> None:
        """Update batch bar when selection changes."""
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
        """Execute a batch action on all selected clips."""
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
        """Clear selection and hide batch bar."""
        self._list_view.clearSelection()
        self._batch_bar.setVisible(False)

    def enter_selection_mode(self) -> None:
        """Programmatically enter selection mode."""
        self._list_view.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )

    def _invert_selection(self) -> None:
        """Invert the current selection — selected become deselected and vice versa.

        Uses :meth:`QItemSelectionModel.select` with
        :attr:`~QItemSelectionModel.SelectionFlag.Toggle` on every row,
        which efficiently flips the selection without rebuilding indices.

        .. note::
            If no clips are selected this selects everything (same as Ctrl+A).
            If everything is selected this deselects everything.
        """
        sel_model = self._list_view.selectionModel()
        if sel_model is None:
            return

        row_count = self._proxy_model.rowCount()
        if row_count == 0:
            return

        # Block signals to avoid N redundant _on_selection_changed callbacks
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

        # Fire selection-changed callback once after the bulk toggle
        self._on_selection_changed()

    def focus_search(self) -> None:
        """Set keyboard focus on the search bar."""
        self._search_input.setFocus()
        self._search_input.selectAll()

    # ==================================================================
    # Empty / error states
    # ==================================================================

    def _build_empty_state(self) -> QWidget:
        """Build the centered empty-state widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("—")
        icon.setObjectName("pageTitle")
        icon.setStyleSheet("font-size: 48px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self._empty_label = QLabel()
        self._empty_label.setObjectName("muted")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shortcuts_btn = QPushButton("View Shortcuts")
        shortcuts_btn.clicked.connect(lambda: self.empty_action_requested.emit("View Shortcuts"))
        btn_layout.addWidget(shortcuts_btn)
        capture_btn = QPushButton("Capture Settings")
        capture_btn.clicked.connect(lambda: self.empty_action_requested.emit("Capture Settings"))
        btn_layout.addWidget(capture_btn)
        layout.addLayout(btn_layout)

        widget.setVisible(False)
        return widget

    def _build_error_state(self) -> QWidget:
        """Build the centered error-state widget."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("!")
        icon.setObjectName("pageTitle")
        icon.setStyleSheet("font-size: 48px; color: var(--accent-red);")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self._error_label = QLabel()
        self._error_label.setObjectName("muted")
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
        """Hide all state overlays (empty, error)."""
        if self._empty_widget:
            self._empty_widget.setVisible(False)
        if self._error_widget:
            self._error_widget.setVisible(False)

    def _show_empty(self, message: str) -> None:
        """Display the empty state with the given message."""
        self._list_view.setVisible(False)
        self._batch_bar.setVisible(False)
        if self._error_widget:
            self._error_widget.setVisible(False)

        self._empty_label.setText(message)
        if self._empty_widget:
            self._empty_widget.setVisible(True)

    def _show_error(self, message: str) -> None:
        """Display the error state with the given message and a retry button."""
        self._list_view.setVisible(False)
        self._batch_bar.setVisible(False)
        if self._empty_widget:
            self._empty_widget.setVisible(False)

        self._error_label.setText(message)
        if self._error_widget:
            self._error_widget.setVisible(True)

    # ==================================================================
    # Skeleton cards (async loading placeholders)
    # ==================================================================

    def _show_skeletons(self, count: int = 8) -> None:
        """Show skeleton card placeholders during async loading."""
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

        # Insert the skeleton container where the list view would be
        parent_layout = self.layout()
        if parent_layout is not None:
            list_idx = parent_layout.indexOf(self._list_view)
            if list_idx >= 0:
                parent_layout.insertWidget(list_idx, self._skeleton_container)

        self._skeleton_container.setVisible(True)

    def _remove_skeletons(self) -> None:
        """Remove all skeleton cards and the container."""
        for card in self._skeleton_cards:
            card.deleteLater()
        self._skeleton_cards.clear()
        if self._skeleton_container is not None:
            self._skeleton_container.deleteLater()
            self._skeleton_container = None

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def keyPressEvent(self, event) -> None:
        """Handle keyboard shortcuts."""
        key = event.key()
        mods = event.modifiers()

        if mods == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_F:
                self._search_input.setFocus()
                self._search_input.selectAll()
            elif key == Qt.Key.Key_A:
                self._list_view.selectAll()
            elif key == Qt.Key.Key_B:
                self.enter_selection_mode()
            return

        # Escape is now handled context-aware by MainWindow._on_escape()
        # via a global QShortcut, which checks search text and batch bar
        # before falling through to page switch.
        if key == Qt.Key.Key_Escape:
            return

        super().keyPressEvent(event)

    # ==================================================================
    # Context menu
    # ==================================================================

    def contextMenuEvent(self, event) -> None:
        """Show right-click context menu for the clip under the cursor."""
        # Find the clip under the mouse cursor
        index = self._list_view.indexAt(event.pos())
        if not index.isValid():
            return

        source_idx = self._proxy_model.mapToSource(index)
        data = source_idx.data(Qt.ItemDataRole.UserRole)
        if not data or "id" not in data:
            return

        # Build a lightweight Clip for ContextMenuBuilder
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

        # Connect builder signals to grid page signals
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
