"""Main window — QMainWindow with toolbar island, page stack, and status bar.

Manages navigation between pages (Grid, Player, Stats, Trash, Webhooks)
via a ``QStackedWidget``.  The toolbar island provides nav buttons,
a search bar, and sort controls.  The status bar shows pipeline state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
    ("Record", _PAGE_RECORD),
    ("Grid", _PAGE_GRID),
    ("Player", _PAGE_PLAYER),
    ("Stats", _PAGE_STATS),
    ("Trash", _PAGE_TRASH),
    ("Webhook", _PAGE_WEBHOOK),
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

        # --- Toolbar island ---
        toolbar = self._build_toolbar()
        central_layout.addWidget(toolbar)

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
        self._stack.setCurrentIndex(_PAGE_RECORD)

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
            btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
            nav_layout.addWidget(btn)
            self._nav_buttons[idx] = btn

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
        logger.info("Batch action '%s' on %d clips — not yet fully implemented",
                    action, len(clip_ids))

        if action == "Delete" and self._store is not None:
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
        """Update the status bar with pipeline state.

        Args:
            status_text: Human-readable status (e.g. "Encoding clip-1.mp4").
        """
        self._update_status(status_text)

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
        # Ctrl+F -> focus search (handled by grid page)
        # Ctrl+B -> batch select mode
        shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        shortcut.activated.connect(self._grid_page.enter_selection_mode)

        # Esc -> back to grid from any page
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(lambda: self._switch_page(_PAGE_GRID))

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
