"""Main window — QMainWindow with toolbar island, page stack, and status bar.

Manages navigation between pages (Grid, Player, Stats, Trash, Webhooks)
via a ``QStackedWidget``.  The toolbar island provides nav buttons,
a search bar, and sort controls.  The status bar shows pipeline state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# Page indices
_PAGE_GRID = 0
_PAGE_RECORD = 1
_PAGE_PLAYER = 2
_PAGE_STATS = 3
_PAGE_TRASH = 4
_PAGE_WEBHOOK = 5

_NAV_BUTTONS = [
    ("&Recording", _PAGE_RECORD),
    ("&Grid", _PAGE_GRID),
    ("&Player", _PAGE_PLAYER),
    ("&Stats", _PAGE_STATS),
    ("&Trash", _PAGE_TRASH),
    ("&Webhooks", _PAGE_WEBHOOK),
]


class MainWindow(QMainWindow):
    """Main application window with page stack and toolbar island.

    Signals:
        close_to_tray: Emitted when the window should hide to tray
            instead of quitting.
    """

    close_to_tray = pyqtSignal()

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._minimize_to_tray = True

        # Window properties
        self.setWindowTitle("moment")
        self.setAccessibleName("Moment — Game Clip Manager")
        self.setAccessibleDescription("GPU-accelerated game clip recording and management")
        self.resize(950, 650)
        self.setMinimumSize(680, 400)

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
        self._unavailable_banner = self._build_unavailable_banner()
        central_layout.addWidget(self._unavailable_banner)
        self._unavailable_banner.setVisible(self._store is None)

        # --- Toolbar island ---
        toolbar = self._build_toolbar()
        central_layout.addWidget(toolbar)

        # --- Processing banner (pipeline progress) ---
        from moment.ui.widgets.processing_banner import ProcessingBanner
        self._processing_banner = ProcessingBanner()
        self._processing_banner.setVisible(False)
        central_layout.addWidget(self._processing_banner)

        # --- Page stack ---
        self._stack = QStackedWidget()
        central_layout.addWidget(self._stack, stretch=1)

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

    def _build_unavailable_banner(self) -> QWidget:
        """Build a banner widget shown when the store is unavailable."""
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

        icon_label = QLabel("⚠")
        icon_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        banner_layout.addWidget(icon_label)

        msg_label = QLabel("Service unavailable — database could not be opened.  "
                          "Check that ~/.config/moment/clips.db is accessible.")
        msg_label.setStyleSheet("color: white; font-size: 13px;")
        msg_label.setWordWrap(True)
        banner_layout.addWidget(msg_label, stretch=1)

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
        """Attempt to re-initialise the store on retry click."""
        logger.info("Retry store initialisation requested")
        # For now, just log — the parent AppManager would need to handle
        # re-initialisation.  This button serves as user-visible signal
        # that something is wrong.
        from moment.ui.widgets.toast import toast_manager
        toast_manager.show_toast(
            "info", "Restart required",
            "Please restart Moment to retry database connection.",
        )

    def _set_nav_enabled(self, enabled: bool) -> None:
        """Enable or disable all navigation buttons."""
        for btn in self._nav_buttons.values():
            btn.setEnabled(enabled)

    # ==================================================================
    # Toolbar
    # ==================================================================

    def _build_toolbar(self) -> QWidget:
        """Build the floating island toolbar with nav buttons."""
        outer = QWidget()
        outer.setObjectName("toolbarOuter")
        outer.setStyleSheet("""
            QWidget#toolbarOuter {
                background-color: var(--bg-window);
                border-bottom: 1px solid var(--border-window);
            }
        """)
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(12, 6, 12, 6)
        outer_layout.setSpacing(8)

        # Left: nav buttons in a floating island group
        nav_island = QFrame()
        nav_island.setObjectName("toolbarIsland")
        nav_layout = QHBoxLayout(nav_island)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(2)

        self._nav_buttons: dict[int, QToolButton] = {}
        for label, idx in _NAV_BUTTONS:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
            # Accessible names
            a11y_labels = {
                _PAGE_RECORD: "Recording View",
                _PAGE_GRID: "Grid View",
                _PAGE_PLAYER: "Player",
                _PAGE_STATS: "Statistics",
                _PAGE_TRASH: "Trash",
                _PAGE_WEBHOOK: "Webhooks",
            }
            btn.setAccessibleName(a11y_labels.get(idx, label))
            nav_layout.addWidget(btn)
            self._nav_buttons[idx] = btn

        # Tab order: nav buttons in a logical chain
        for i in range(len(_NAV_BUTTONS) - 1):
            _, curr_idx = _NAV_BUTTONS[i]
            _, next_idx = _NAV_BUTTONS[i + 1]
            self.setTabOrder(
                self._nav_buttons[curr_idx],
                self._nav_buttons[next_idx],
            )

        outer_layout.addWidget(nav_island)

        # Spacer
        outer_layout.addStretch()

        return outer

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
    # Page navigation
    # ==================================================================

    def _switch_page(self, index: int) -> None:
        """Switch the stacked widget to the given page index."""
        # Update nav button states
        for i, btn in self._nav_buttons.items():
            btn.setChecked(i == index)

        self._stack.setCurrentIndex(index)

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

        if action == "Delete" and self._store is not None:
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
        self._recording_page.set_recording()

    def _on_stop_recording(self) -> None:
        """Handle stop-recording from the recording page."""
        logger.info("Stop recording requested")
        self._recording_page.set_ready()

    def _on_recording_save_clip(self, duration: int) -> None:
        """Handle save-clip from the recording page."""
        logger.info("Save %ds clip requested from recording page", duration)

    def _on_trash_changed(self) -> None:
        """Handle trash change — refresh grid."""
        logger.debug("Trash changed")
        self._grid_page.refresh()

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
                player._play_btn.setText("▶")
                return
            # Check if editor window is open
            if player._editor is not None and player._editor.isVisible():
                player._editor.close()
                return

        # 3. Grid page: clear search first, then exit selection mode
        if current_idx == _PAGE_GRID and self._grid_page is not None:
            if self._grid_page._search_input.text():
                self._grid_page._search_input.clear()
                return
            if self._grid_page._batch_bar.isVisible():
                self._grid_page._exit_selection_mode()
                return

        # 5. Switch to Grid (default)
        self._switch_page(_PAGE_GRID)

    def _focus_grid_search(self) -> None:
        """Set keyboard focus on the grid search bar after the window is shown."""
        self._grid_page.focus_search()

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
