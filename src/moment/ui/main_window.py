"""Main window — QMainWindow with left sidebar nav, top toolbar, page stack, and status bar.

Manages navigation between pages (Grid, Player, Stats, Trash, Webhooks)
via a ``QStackedWidget``.  The left sidebar provides icon+label nav
buttons inspired by Medal.tv's desktop aesthetic.  A top toolbar panel
(ONLYOFFICE-style) shows context-sensitive action groups above the page
stack.  The status bar shows pipeline state.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.config import Config
    from moment.core.pipeline import Pipeline
    from moment.core.store import Store
    from moment.core.gsr_controller import GSRController

logger = logging.getLogger(__name__)

# Page indices
_PAGE_GRID = 0
_PAGE_RECORD = 1
_PAGE_PLAYER = 2
_PAGE_STATS = 3
_PAGE_TRASH = 4
_PAGE_WEBHOOK = 5

# Sidebar navigation items: (label, page_index) — no emoji, text-only
_NAV_ITEMS: list[tuple[str, int]] = [
    ("Library", _PAGE_GRID),
    ("Record", _PAGE_RECORD),
    ("Player", _PAGE_PLAYER),
    ("Stats", _PAGE_STATS),
    ("Trash", _PAGE_TRASH),
    ("Webhooks", _PAGE_WEBHOOK),
]


class MainWindow(QMainWindow):
    """Main application window with page stack and toolbar island.

    Signals:
        close_to_tray: Emitted when the window should hide to tray
            instead of quitting.
        store_retry_requested: Emitted when the user clicks Retry on
            the unavailable-store banner.
    """

    close_to_tray = pyqtSignal()
    store_retry_requested = pyqtSignal()

    # Sidebar width constant
    SIDEBAR_W = 76

    def __init__(self, store: "Store | None" = None, parent=None,
                 store_init_error: str | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._store_init_error = store_init_error
        self._minimize_to_tray = True

        # Core service references (set by AppManager after construction)
        self._pipeline: "Pipeline | None" = None
        self._gsr_controller: "GSRController | None" = None
        self._config: "Config | None" = None
        self._app_manager = None  # AppManager reference
        self._recording_controller = None  # RecorderController (lazy init)

        # Window properties
        self.setWindowTitle("moment")
        self.setAccessibleName("Moment — Game Clip Manager")
        self.setAccessibleDescription("GPU-accelerated game clip recording and management")
        self.resize(950, 650)
        self.setMinimumSize(720, 420)

        # Center on primary screen
        screen = QApplication.primaryScreen()
        if screen is not None:
            center = screen.availableGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())

        # --- Central widget ---
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # --- Service unavailable banner (shown when store is None) ---
        self._unavailable_banner = self._build_unavailable_banner(
            self._store_init_error or ""
        )
        central_layout.addWidget(self._unavailable_banner)
        self._unavailable_banner.setVisible(self._store is None)

        # --- Content area: sidebar + content (horizontal split) ---
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        # Left sidebar
        self._sidebar = self._build_sidebar()
        content_row.addWidget(self._sidebar)

        # Right content area
        right_area = QVBoxLayout()
        right_area.setContentsMargins(0, 0, 0, 0)
        right_area.setSpacing(0)

        # Processing banner (pipeline progress)
        from moment.ui.widgets.processing_banner import ProcessingBanner
        self._processing_banner = ProcessingBanner()
        self._processing_banner.setVisible(False)
        right_area.addWidget(self._processing_banner)

        # Top toolbar panel (ONLYOFFICE-style ribbon)
        self._toolbar_panel = self._build_toolbar_panel()
        right_area.addWidget(self._toolbar_panel)

        # Page stack
        self._stack = QStackedWidget()
        right_area.addWidget(self._stack, stretch=1)

        content_row.addLayout(right_area, stretch=1)
        central_layout.addLayout(content_row, stretch=1)

        # --- Status bar ---
        self._status_bar = QStatusBar()
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("statusBarLabel")
        self._status_bar.addWidget(self._status_label)
        self.setStatusBar(self._status_bar)

        # --- Create pages ---
        self._create_pages()

        # --- Keyboard shortcuts ---
        self._setup_shortcuts()

        # Show grid by default
        self._nav_buttons[_PAGE_GRID].setChecked(True)
        self._stack.setCurrentIndex(_PAGE_GRID)

        # Disable nav buttons if store is unavailable
        if self._store is None:
            self._set_nav_enabled(False)

        # Set keyboard focus on the search bar once the window is shown
        QTimer.singleShot(0, self._focus_grid_search)

    # ==================================================================
    # Service unavailable banner
    # ==================================================================

    def _build_unavailable_banner(self, error_message: str) -> QWidget:
        """Build a banner widget shown when the store is unavailable.

        Args:
            error_message: The actual error message from the failed
                Store initialisation, displayed in the banner.
        """
        banner = QFrame()
        banner.setObjectName("unavailableBanner")
        banner.setStyleSheet("""
            QFrame#unavailableBanner {
                background-color: var(--accent-red);
                border: none;
                border-radius: 0;
            }
        """)
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 8, 16, 8)
        banner_layout.setSpacing(8)

        icon_label = QLabel("!")
        icon_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold; background: transparent;")
        banner_layout.addWidget(icon_label)

        # Build a descriptive message from the actual error
        if error_message:
            display_msg = error_message
        else:
            display_msg = "Service unavailable — database could not be opened."

        msg_label = QLabel(display_msg)
        msg_label.setStyleSheet("color: white; font-size: 13px;")
        msg_label.setWordWrap(True)
        banner_layout.addWidget(msg_label, stretch=1)

        # Show Log button — opens the log file in the system editor
        show_log_btn = QPushButton("Show Log")
        show_log_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px;
                color: white;
                padding: 4px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.3);
            }
        """)
        log_path = os.path.expanduser("~/.local/share/moment/moment.log")
        show_log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(log_path))
        )
        banner_layout.addWidget(show_log_btn)

        # Retry button — tries to re-initialise the store
        retry_btn = QPushButton("Retry")
        retry_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px;
                color: white;
                padding: 4px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.3);
            }
        """)
        retry_btn.clicked.connect(self._on_retry_store)
        banner_layout.addWidget(retry_btn)

        return banner

    def _on_retry_store(self) -> None:
        """Attempt to re-initialise the store on retry click.

        If ``_app_manager`` is set, delegates to its ``retry_store()``
        method for a live re-initialisation.  Otherwise falls back to
        a restart-required toast.
        """
        logger.info("Retry store initialisation requested")
        if self._app_manager is not None:
            self._app_manager.retry_store()
        else:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "info", "Restart required",
                "Please restart Moment to retry database connection.",
            )

    def on_store_recovered(self) -> None:
        """Called when the store is successfully re-initialised.

        Hides the unavailable banner, enables navigation, and refreshes
        the grid page.
        """
        self._store = self._app_manager._store if self._app_manager else None
        self._store_init_error = None

        if self._store is not None:
            self._unavailable_banner.setVisible(False)
            self._set_nav_enabled(True)
            # Update store reference on all pages that depend on it
            self._grid_page._store = self._store
            self._grid_page.refresh()
            self._player_page._store = self._store
            self._stats_page._store = self._store
            self._trash_page._store = self._store
            self._webhook_page._store = self._store
            self._update_status("Store reconnected")

            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "success", "Store reconnected",
                "Database connection re-established.",
            )

    def _set_nav_enabled(self, enabled: bool) -> None:
        """Enable or disable all navigation buttons."""
        for btn in self._nav_buttons.values():
            btn.setEnabled(enabled)

    # ==================================================================
    # Sidebar
    # ==================================================================

    def _build_sidebar(self) -> QWidget:
        """Build the left sidebar with icon+label nav buttons."""
        sidebar = QFrame()
        sidebar.setObjectName("sidebarWidget")
        sidebar.setFixedWidth(self.SIDEBAR_W)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(4, 12, 4, 12)
        sidebar_layout.setSpacing(2)

        self._nav_buttons: dict[int, QPushButton] = {}

        a11y_labels = {
            _PAGE_RECORD: "Recording View",
            _PAGE_GRID: "Library",
            _PAGE_PLAYER: "Player",
            _PAGE_STATS: "Statistics",
            _PAGE_TRASH: "Trash",
            _PAGE_WEBHOOK: "Webhooks",
        }

        for label, idx in _NAV_ITEMS:
            # Text-only button (no emoji icons)
            btn = QPushButton(label)
            btn.setObjectName("sidebarNav")
            btn.setCheckable(True)
            btn.setFixedSize(68, 36)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
            btn.setAccessibleName(a11y_labels.get(idx, label))

            sidebar_layout.addWidget(btn)
            self._nav_buttons[idx] = btn

        # Tab order: nav buttons in a logical chain
        for i in range(len(_NAV_ITEMS) - 1):
            _, curr_idx = _NAV_ITEMS[i]
            _, next_idx = _NAV_ITEMS[i + 1]
            self.setTabOrder(
                self._nav_buttons[curr_idx],
                self._nav_buttons[next_idx],
            )

        sidebar_layout.addStretch()
        return sidebar

    # ==================================================================
    # Pages
    # ==================================================================

    def _create_pages(self) -> None:
        """Create and add all pages to the stack."""
        from moment.ui.pages.grid_page import GridPage
        from moment.ui.pages.player_page import PlayerPage
        from moment.ui.pages.recording_page import RecordingPage
        from moment.ui.pages.stats_page import StatsPage
        from moment.ui.pages.trash_page import TrashPage
        from moment.ui.pages.webhook_page import WebhookPage

        # Recording (default landing page)
        self._recording_page = RecordingPage()
        self._recording_page.start_recording.connect(self._on_start_recording)
        self._recording_page.stop_recording.connect(self._on_stop_recording)
        self._recording_page.save_clip.connect(self._on_recording_save_clip)
        self._stack.addWidget(self._recording_page)

        # Grid
        self._grid_page = GridPage(self._store)
        self._grid_page.clip_activated.connect(self._on_clip_activated)
        self._grid_page.batch_action_requested.connect(self._on_batch_action)
        self._grid_page.selection_changed.connect(self._on_grid_selection_changed)
        self._grid_page.empty_action_requested.connect(self._on_empty_action)
        self._grid_page.files_dropped.connect(self._on_files_dropped)
        self._stack.addWidget(self._grid_page)

        # Player
        self._player_page = PlayerPage(self._store)
        self._player_page.back_requested.connect(lambda: self._switch_page(_PAGE_GRID))
        self._stack.addWidget(self._player_page)

        # Stats
        self._stats_page = StatsPage(self._store)
        self._stats_page.clip_activated.connect(self._on_clip_activated)
        self._stack.addWidget(self._stats_page)

        # Trash
        self._trash_page = TrashPage(self._store)
        self._trash_page.clip_restored.connect(self._on_clip_restored)
        self._trash_page.clips_removed.connect(self._on_trash_changed)
        self._stack.addWidget(self._trash_page)

        # Webhooks
        self._webhook_page = WebhookPage(self._store)
        self._stack.addWidget(self._webhook_page)

    # ==================================================================
    # Top toolbar panel (ONLYOFFICE-style)
    # ==================================================================

    def _build_toolbar_panel(self) -> QWidget:
        """Build the context-sensitive top toolbar panel."""
        panel = QFrame()
        panel.setObjectName("toolbarPanel")
        panel.setStyleSheet("""
            QFrame#toolbarPanel {
                background-color: var(--bg-surface);
                border-bottom: 1px solid var(--border-window);
                padding: 6px 12px;
                min-height: 40px;
            }
        """)
        self._toolbar_layout = QHBoxLayout(panel)
        self._toolbar_layout.setContentsMargins(12, 4, 12, 4)
        self._toolbar_layout.setSpacing(8)

        # Global search bar (always visible, filters grid when active)
        self._toolbar_search = QLineEdit()
        self._toolbar_search.setPlaceholderText("Search clips…")
        self._toolbar_search.setClearButtonEnabled(True)
        self._toolbar_search.setFixedWidth(240)
        self._toolbar_search.setVisible(False)
        self._toolbar_layout.addWidget(self._toolbar_search)

        # Sort dropdown
        self._toolbar_sort = QComboBox()
        self._toolbar_sort.addItems(["Newest first", "Oldest first", "Largest file",
                                      "Smallest file", "Longest", "Shortest", "A-Z", "Z-A"])
        self._toolbar_sort.setVisible(False)
        self._toolbar_layout.addWidget(self._toolbar_sort)

        # Action group separator
        self._toolbar_sep = QFrame()
        self._toolbar_sep.setFrameShape(QFrame.Shape.VLine)
        self._toolbar_sep.setStyleSheet("color: var(--border-menu);")
        self._toolbar_sep.setVisible(False)
        self._toolbar_layout.addWidget(self._toolbar_sep)

        # Page-specific action buttons container
        self._toolbar_actions: list[QPushButton] = []

        self._toolbar_layout.addStretch()
        return panel

    def _clear_toolbar_actions(self) -> None:
        """Remove all page-specific toolbar action buttons."""
        for btn in self._toolbar_actions:
            self._toolbar_layout.removeWidget(btn)
            btn.deleteLater()
        self._toolbar_actions.clear()

    def _add_toolbar_action(self, text: str, callback, obj_name: str = "") -> QPushButton:
        """Add a button to the toolbar and return it."""
        btn = QPushButton(text)
        if obj_name:
            btn.setObjectName(obj_name)
        btn.clicked.connect(callback)
        # Insert before the stretch
        self._toolbar_layout.insertWidget(
            self._toolbar_layout.count() - 1, btn,
        )
        self._toolbar_actions.append(btn)
        return btn

    def _update_toolbar(self, index: int) -> None:
        """Update the toolbar panel for the given page index."""
        self._clear_toolbar_actions()

        if index == _PAGE_GRID:
            self._toolbar_search.setVisible(True)
            self._toolbar_sort.setVisible(True)
            self._toolbar_sep.setVisible(True)

            # Wire search directly to grid proxy filter (bypass debounce since
            # toolbar text IS the authoritative search input)
            try:
                self._toolbar_search.textChanged.disconnect()
            except TypeError:
                pass
            self._toolbar_search.textChanged.connect(
                self._grid_page._proxy_model.set_filter_text
            )

            # Wire sort to grid page
            try:
                self._toolbar_sort.currentTextChanged.disconnect()
            except TypeError:
                pass
            self._toolbar_sort.currentTextChanged.connect(
                self._grid_page._on_sort_changed
            )

            # Refresh button
            self._add_toolbar_action(
                "Refresh", self._grid_page.refresh,
            )

        elif index == _PAGE_RECORD:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self._toolbar_sep.setVisible(False)

            self._add_toolbar_action(
                "Save 15s", lambda: self._recording_page.save_clip.emit(15),
            )
            self._add_toolbar_action(
                "Save 30s", lambda: self._recording_page.save_clip.emit(30),
            )
            self._add_toolbar_action(
                "Save 60s", lambda: self._recording_page.save_clip.emit(60),
            )

        elif index == _PAGE_PLAYER:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self._toolbar_sep.setVisible(False)

            self._add_toolbar_action(
                "Back", self._player_page.back_requested.emit,
            )

        elif index == _PAGE_STATS:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self._toolbar_sep.setVisible(False)

            self._add_toolbar_action(
                "Refresh", self._stats_page.refresh,
            )

        elif index == _PAGE_TRASH:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self._toolbar_sep.setVisible(False)

            self._add_toolbar_action(
                "Refresh", self._trash_page.refresh,
            )

        elif index == _PAGE_WEBHOOK:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self._toolbar_sep.setVisible(False)

            self._add_toolbar_action(
                "Refresh", self._webhook_page.refresh,
            )

    # ==================================================================
    # Page navigation
    # ==================================================================

    def _switch_page(self, index: int) -> None:
        """Switch the stacked widget to the given page index."""
        # Update nav button states
        for i, btn in self._nav_buttons.items():
            btn.setChecked(i == index)

        self._stack.setCurrentIndex(index)

        # Update toolbar for the new page
        self._update_toolbar(index)

        # Refresh pages when switching to them
        if index == _PAGE_RECORD:
            pass  # Recording page is stateless
        elif index == _PAGE_GRID:
            self._grid_page.refresh()
        elif index == _PAGE_STATS:
            self._stats_page.refresh()
        elif index == _PAGE_TRASH:
            self._trash_page.refresh()
        elif index == _PAGE_WEBHOOK:
            self._webhook_page.refresh()

        # Stop playback when leaving player
        if index != _PAGE_PLAYER:
            self._player_page.stop()

        logger.debug("Switched to page %d", index)

    def show_grid(self) -> None:
        """Navigate to the grid page and refresh."""
        self._switch_page(_PAGE_GRID)

    def show_player(self, clip_id: str) -> None:
        """Navigate to the player page and load a clip.

        Args:
            clip_id: UUID of the clip to load.
        """
        self._switch_page(_PAGE_PLAYER)
        self._player_page.load_clip(clip_id)

    # ==================================================================
    # Signal handlers
    # ==================================================================

    def _on_clip_activated(self, clip_id: str) -> None:
        """Handle click on a clip card — switch to player."""
        self.show_player(clip_id)

    def _on_batch_action(self, action: str, clip_ids: list[str]) -> None:
        """Handle batch operations from the grid page."""
        logger.info("Batch action '%s' on %d clips", action, len(clip_ids))

        if self._store is None:
            logger.warning("Cannot perform batch action: store unavailable")
            return

        if action == "Delete":
            self._batch_delete(clip_ids)
        elif action == "Favorite":
            self._batch_favorite(clip_ids)
        elif action == "Tag":
            self._batch_tag(clip_ids)
        elif action == "Re-encode":
            self._batch_reencode(clip_ids)
        elif action == "Re-upload":
            self._batch_reupload(clip_ids)
        elif action == "Export":
            self._batch_export(clip_ids)
        elif action == "Move to folder":
            self._batch_move_to_folder(clip_ids)

    # ------------------------------------------------------------------
    # Batch action implementations
    # ------------------------------------------------------------------

    def _batch_delete(self, clip_ids: list[str]) -> None:
        """Soft-delete selected clips."""
        reply = QMessageBox.question(
            self, "Delete Clips",
            f"Delete {len(clip_ids)} clip(s)?\n\nThey will be moved to Trash.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for clip_id in clip_ids:
            try:
                self._store.delete_clip(clip_id, soft=True)
            except Exception as exc:
                logger.warning("Failed to delete clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status("Deleted %d clips" % len(clip_ids))

    def _batch_favorite(self, clip_ids: list[str]) -> None:
        """Toggle the favorite flag on selected clips."""
        toggled = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is not None:
                    clip.favorite = not clip.favorite
                    self._store.update_clip(clip)
                    toggled += 1
            except Exception as exc:
                logger.warning("Failed to toggle favorite for %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status(f"Favorited {toggled} clip(s)")

    def _batch_tag(self, clip_ids: list[str]) -> None:
        """Open tag dialog and apply tags to selected clips."""
        from moment.ui.widgets.tag_dialog import TagDialog

        # Pre-populate with tags from the first selected clip
        current_tags: list[str] = []
        if clip_ids:
            try:
                first_clip = self._store.get_clip(clip_ids[0])
                if first_clip is not None:
                    current_tags = list(first_clip.tags)
            except Exception as exc:
                logger.warning("Could not read tags from clip %s: %s", clip_ids[0], exc)

        dlg = TagDialog(current_tags, parent=self)
        if dlg.exec() != TagDialog.DialogCode.Accepted:
            return

        new_tags = dlg.tags()
        applied = 0
        for clip_id in clip_ids:
            try:
                self._store.set_tags(clip_id, new_tags)
                applied += 1
            except Exception as exc:
                logger.warning("Failed to tag clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status(f"Tagged {applied} clip(s)")

    def _batch_reencode(self, clip_ids: list[str]) -> None:
        """Re-enqueue selected clips for encoding."""
        if self._pipeline is None:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "warning", "Pipeline unavailable",
                "Cannot re-encode — pipeline is not running.",
            )
            return

        from moment.core.models import Task, TaskKind

        enqueued = 0
        for clip_id in clip_ids:
            try:
                task = Task(
                    id=str(uuid.uuid4()),
                    type=TaskKind.ENCODE,
                    priority=10,
                    payload={"clip_id": clip_id},
                )
                self._pipeline.enqueue(task)
                enqueued += 1
            except Exception as exc:
                logger.warning("Failed to enqueue encode for %s: %s", clip_id, exc)
        self._update_status(f"Re-encoding {enqueued} clip(s)")

    def _batch_reupload(self, clip_ids: list[str]) -> None:
        """Re-enqueue selected clips for upload."""
        if self._pipeline is None:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "warning", "Pipeline unavailable",
                "Cannot re-upload — pipeline is not running.",
            )
            return

        from moment.core.models import Task, TaskKind

        enqueued = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is None or clip.encoded_path is None:
                    logger.warning(
                        "Cannot re-upload %s: clip not found or not encoded", clip_id,
                    )
                    continue

                task = Task(
                    id=str(uuid.uuid4()),
                    type=TaskKind.UPLOAD,
                    priority=1,
                    payload={
                        "clip_id": clip_id,
                        "path": str(clip.encoded_path),
                    },
                )
                self._pipeline.enqueue(task)
                enqueued += 1
            except Exception as exc:
                logger.warning("Failed to enqueue upload for %s: %s", clip_id, exc)
        self._update_status(f"Re-uploading {enqueued} clip(s)")

    def _batch_export(self, clip_ids: list[str]) -> None:
        """Export selected clips to a user-chosen directory."""
        if len(clip_ids) == 1:
            # Single clip: use Save File dialog
            clip = self._store.get_clip(clip_ids[0])
            if clip is None:
                return
            src = clip.encoded_path or clip.source_path
            dest, _ = QFileDialog.getSaveFileName(
                self, "Export Clip", str(src.name), "Video Files (*.mp4 *.mkv)",
            )
            if not dest:
                return
            try:
                shutil.copy2(str(src), dest)
                self._update_status(f"Exported to {os.path.basename(dest)}")
            except OSError as exc:
                logger.exception("Export failed: %s", exc)
                QMessageBox.warning(
                    self, "Export Failed", f"Could not export clip: {exc}",
                )
        else:
            # Multiple clips: choose directory
            dest_dir = QFileDialog.getExistingDirectory(
                self, "Export Clips to…",
            )
            if not dest_dir:
                return
            exported = 0
            errors = 0
            for clip_id in clip_ids:
                try:
                    clip = self._store.get_clip(clip_id)
                    if clip is None:
                        errors += 1
                        continue
                    src = clip.encoded_path or clip.source_path
                    shutil.copy2(str(src), os.path.join(dest_dir, str(src.name)))
                    exported += 1
                except OSError as exc:
                    logger.exception("Export failed for %s: %s", clip_id, exc)
                    errors += 1
            msg = f"Exported {exported} clip(s)"
            if errors:
                msg += f" — {errors} failed"
            self._update_status(msg)

    def _batch_move_to_folder(self, clip_ids: list[str]) -> None:
        """Move selected clips to a user-chosen folder."""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Move Clips to Folder…",
        )
        if not folder_path:
            return

        moved = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is not None:
                    clip.folder = folder_path
                    self._store.update_clip(clip)
                    moved += 1
            except Exception as exc:
                logger.warning("Failed to move clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status(f"Moved {moved} clip(s) to folder")

    # ------------------------------------------------------------------
    # Empty state action handler
    # ------------------------------------------------------------------

    def _on_empty_action(self, action: str) -> None:
        """Handle actions from the empty/error state buttons."""
        logger.debug("Empty-state action: %s", action)

        if action == "View Shortcuts":
            self._show_shortcuts_dialog()
        elif action == "Capture Settings":
            self._open_capture_settings()
        elif action == "Reset Database":
            self._confirm_reset_database()
        elif action == "Open Config Folder":
            self._open_config_folder()

    def _show_shortcuts_dialog(self) -> None:
        """Display keyboard shortcut reference."""
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "Moment Keyboard Shortcuts\n\n"
            "Ctrl+F   — Focus search bar\n"
            "Ctrl+A   — Select all clips\n"
            "Ctrl+B   — Enter batch selection mode\n"
            "Ctrl+C   — Copy selected clip URL\n"
            "Esc      — Back / clear selection / exit fullscreen\n"
            "F5       — Refresh current page\n"
            "Del      — Delete selected clips\n\n"
            "Global Hotkeys (when configured):\n"
            "F8       — Save replay / open overlay",
        )

    def _open_capture_settings(self) -> None:
        """Open the settings dialog, falling back to an info message."""
        try:
            from moment.ui.dialogs.settings_dialog import SettingsDialog

            dlg = SettingsDialog(self._config)
            dlg.exec()
        except Exception as exc:
            logger.exception("Could not open settings dialog: %s", exc)
            QMessageBox.information(
                self, "Capture Settings",
                "Capture settings can be configured in the Settings dialog "
                "(accessible from the system tray icon menu).",
            )

    def _confirm_reset_database(self) -> None:
        """Confirm and reset the database."""
        if self._store is None:
            return

        reply = QMessageBox.warning(
            self, "Reset Database",
            "This will permanently delete ALL clips, tags, webhooks, "
            "and settings from the database.\n\n"
            "This action cannot be undone.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Second confirmation
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self, "Reset Database — Final Confirmation",
            "Type DELETE to confirm:",
        )
        if not ok or text.strip() != "DELETE":
            return

        try:
            self._store.close()
            db_path = os.path.join(
                self._config.get_path("db_dir") if self._config
                else os.path.expanduser("~/.config/moment"),
                "clips.db",
            )
            if os.path.isfile(db_path):
                os.remove(db_path)
                logger.info("Database file removed: %s", db_path)
            # Also remove WAL/SHM files
            for suffix in ("-wal", "-shm"):
                wal_path = db_path + suffix
                if os.path.isfile(wal_path):
                    os.remove(wal_path)

            QMessageBox.information(
                self, "Database Reset",
                "Database has been reset. Please restart Moment "
                "to create a fresh database.",
            )
            self._update_status("Database reset — restart required")
        except Exception as exc:
            logger.exception("Database reset failed: %s", exc)
            QMessageBox.critical(
                self, "Reset Failed",
                f"Could not reset the database: {exc}",
            )

    def _open_config_folder(self) -> None:
        """Open the Moment config directory in the system file manager."""
        config_dir = os.path.expanduser("~/.config/moment")
        QDesktopServices.openUrl(QUrl.fromLocalFile(config_dir))

    def _on_grid_selection_changed(self, count: int) -> None:
        """Handle grid selection changes — update status bar."""
        if count > 0:
            self._update_status(f"{count} clip(s) selected")
        else:
            self._update_status("Ready")

    # ==================================================================
    # Status bar
    # ==================================================================

    def _update_status(self, text: str) -> None:
        """Update the status bar text."""
        self._status_label.setText(text)
        self._status_bar.showMessage(text, 5000)

    def set_pipeline_status(self, status_text: str) -> None:
        """Update the status bar and processing banner with pipeline state.

        Parses the status string from :meth:`Pipeline.get_status` to extract
        per-stage counts and updates both the status bar label and the
        processing banner widget.

        Args:
            status_text: Human-readable status (e.g. ``"Encoding 1 • Uploading 2"``).
        """
        self._update_status(status_text)
        if hasattr(self, "_processing_banner") and self._processing_banner is not None:
            self._update_banner(status_text)

    def _update_banner(self, status_text: str) -> None:
        """Translate pipeline status string into a ProcessingBanner update."""
        banner = self._processing_banner
        if status_text == "Idle" or not status_text.strip():
            banner.update_status("idle")
            return

        # Count active stages from status segments like "Encoding 2•Uploading 1•Thumbnails 3"
        counts: dict[str, int] = {}
        segments = status_text.replace("•", "|").replace(",", "|").split("|")
        for segment in segments:
            segment = segment.strip()
            parts = segment.split()
            if len(parts) >= 2:
                try:
                    counts[parts[0].lower()] = int(parts[1])
                except ValueError:
                    pass

        if "(paused)" in status_text and not counts:
            banner.update_status("idle")
            return

        # Build a combined status so all active stages are visible
        parts: list[str] = []
        if counts.get("encoding", 0) > 0:
            parts.append(f"Encoding {counts['encoding']}")
        if counts.get("uploading", 0) > 0:
            parts.append(f"Uploading {counts['uploading']}")
        if counts.get("thumbnails", 0) > 0:
            parts.append(f"Thumbnails {counts['thumbnails']}")

        if parts:
            banner.update_status(
                "mixed", sum(counts.values()), sum(counts.values()),
            )
            # Override the label to show all stages explicitly
            banner._label.setText(" — ".join(parts))
        else:
            banner.update_status("idle")

    # ==================================================================
    # State
    # ==================================================================

    def set_minimize_to_tray(self, enabled: bool) -> None:
        """Set whether closing the window should hide to tray.

        Args:
            enabled: If ``True``, close hides to tray; otherwise quits.
        """
        self._minimize_to_tray = enabled

    def refresh(self) -> None:
        """Refresh the currently visible page."""
        self._grid_page.refresh()

    # ==================================================================
    # Window events
    # ==================================================================

    def closeEvent(self, event) -> None:
        """Handle window close — hide to tray or quit."""
        if self._minimize_to_tray:
            event.ignore()
            self.hide()
            self.close_to_tray.emit()
            logger.debug("Window hidden to tray")
        else:
            event.accept()

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def _setup_shortcuts(self) -> None:
        """Register global window shortcuts."""
        # Ctrl+F -> focus search
        ctrl_f = QShortcut(QKeySequence("Ctrl+F"), self)
        ctrl_f.activated.connect(self._focus_grid_search)

        # Ctrl+B -> batch select mode (guarded against null store)
        ctrl_b = QShortcut(QKeySequence("Ctrl+B"), self)
        ctrl_b.activated.connect(self._on_ctrl_b)

        # Esc -> context-aware back navigation
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._on_escape)

    # ==================================================================
    # Page-specific signal handlers
    # ==================================================================

    def _on_clip_restored(self, clip_id: str) -> None:
        """Handle clip restore from trash — refresh grid."""
        logger.debug("Clip restored: %s", clip_id)
        self._grid_page.refresh()

    # ==================================================================
    # Recording page signal handlers
    # ==================================================================

    def _on_start_recording(self) -> None:
        """Handle start-recording from the recording page."""
        logger.info("Start recording requested")

        # Initialise RecordingController if not already running
        if self._gsr_controller is None and self._config is not None:
            try:
                from moment.core.recorder_controller import RecorderController

                self._recording_controller = RecorderController(
                    output_dir=self._config.get_path("recordings_dir"),
                    default_fps=int(
                        self._config.get_gsr_setting("replay_fps") or 60
                    ),
                    default_duration=int(
                        self._config.get_gsr_setting("replay_duration") or 30
                    ),
                )
                self._recording_controller.start_recording()
                logger.info("RecordingController started")
            except Exception as exc:
                logger.exception("Failed to start RecordingController: %s", exc)
                from moment.ui.widgets.toast import toast_manager
                toast_manager.show_toast(
                    "error", "Recording failed", str(exc),
                )
                return
        elif self._gsr_controller is not None:
            # GSR instant replay is already running — just update UI
            logger.info("GSR instant replay already active")

        self._recording_page.set_recording()

    def _on_stop_recording(self) -> None:
        """Handle stop-recording from the recording page."""
        logger.info("Stop recording requested")

        if self._recording_controller is not None:
            try:
                self._recording_controller.stop_recording()
            except Exception as exc:
                logger.warning("Error stopping recording: %s", exc)

        self._recording_page.set_ready()

    def _on_recording_save_clip(self, duration: int) -> None:
        """Handle save-clip from the recording page."""
        logger.info("Save %ds clip requested from recording page", duration)

        saved = False

        # Try GSR controller first (instant replay mode)
        if self._gsr_controller is not None:
            try:
                self._gsr_controller.save_replay()
                saved = True
            except Exception as exc:
                logger.exception("GSR save_replay failed: %s", exc)

        # Fall back to RecordingController (manual recording mode)
        if not saved and self._recording_controller is not None:
            try:
                self._recording_controller.save_replay(duration)
                saved = True
            except Exception as exc:
                logger.exception("RecordingController save_replay failed: %s", exc)

        if saved:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "success", "Clip saved", f"{duration}s replay saved",
            )

    def _on_trash_changed(self) -> None:
        """Handle trash change — refresh grid."""
        logger.debug("Trash changed")
        self._grid_page.refresh()

    def _on_files_dropped(self, paths: list[Path]) -> None:
        """Handle video files dropped onto the grid — import them as clips.

        Uses :class:`ImportExport` to validate, copy, probe, thumbnail,
        and insert each dropped file as a new clip.

        Args:
            paths: List of :class:`Path` objects (already filtered for
                valid video extensions by ``_DragDropListView``).
        """
        if self._store is None:
            logger.warning("Cannot import dropped files: store unavailable")
            return

        from moment.core.import_export import ImportExport

        importer = ImportExport(self._store)
        imported = 0
        errors = 0

        self._update_status(f"Importing {len(paths)} file(s)…")

        for path in paths:
            try:
                importer.import_file(path, copy=True, re_encode=False)
                imported += 1
                logger.info("Imported dropped file: %s", path.name)
            except Exception as exc:
                errors += 1
                logger.warning("Failed to import dropped file %s: %s", path.name, exc)

        self._grid_page.refresh()

        if imported > 0:
            self._update_status(f"Imported {imported} clip(s)")
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "success", "Import complete",
                f"Imported {imported} clip(s)" + (
                    f" — {errors} failed" if errors else ""
                ),
            )
        elif errors > 0:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "error", "Import failed",
                f"Could not import {errors} file(s)",
            )

    def _on_ctrl_b(self) -> None:
        """Enter batch selection mode (guarded against null store/grid)."""
        if self._grid_page is not None and self._store is not None:
            self._grid_page.enter_selection_mode()

    def _on_escape(self) -> None:
        """Context-aware Escape handler.

        Priority order:
        1. Player page active + video playing → stop video
        2. Editor window open → close it
        3. Grid page with search text → clear search
        4. Grid selection mode active → exit selection mode
        5. Otherwise → switch to Grid
        """
        current_idx = self._stack.currentIndex()

        # 1. Player page: stop video if playing
        if current_idx == _PAGE_PLAYER:
            player = self._player_page
            if player._fullscreen:
                player._toggle_fullscreen()
                return
            if player._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player._player.pause()
                player._play_btn.setText("Play")
                return
            # Check if editor window is open
            if player._editor is not None and player._editor.isVisible():
                player._editor.close()
                return

        # 3. Grid page: clear search first, then exit selection mode
        if current_idx == _PAGE_GRID and self._grid_page is not None:
            if self._toolbar_search.text():
                self._toolbar_search.clear()
                return
            if self._grid_page._batch_bar.isVisible():
                self._grid_page._exit_selection_mode()
                return

        # 5. Switch to Grid (default)
        self._switch_page(_PAGE_GRID)

    def _focus_grid_search(self) -> None:
        """Set keyboard focus on the toolbar search bar."""
        self._toolbar_search.setFocus()
        self._toolbar_search.selectAll()

    def focus_search(self) -> None:
        """Convenience alias for ``_focus_grid_search``."""
        self._focus_grid_search()

    # ==================================================================
    # Public helpers
    # ==================================================================

    @property
    def recording_page(self):
        """The recording page instance."""
        return self._recording_page

    @property
    def grid_page(self):
        """The grid page instance."""
        return self._grid_page

    @property
    def player_page(self):
        """The player page instance."""
        return self._player_page

    @property
    def stats_page(self):
        """The stats page instance."""
        return self._stats_page

    @property
    def trash_page(self):
        """The trash page instance."""
        return self._trash_page

    @property
    def webhook_page(self):
        """The webhook page instance."""
        return self._webhook_page
