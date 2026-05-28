"""Tray icon — system tray integration with dynamic context menu.

Provides the primary user-facing entry point in the system tray.
Left-click toggles the main window, right-click opens a context
menu with recording actions / recent clips / settings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from clip_tray.ui.resources import load_icon

if TYPE_CHECKING:
    from clip_tray.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

# Replay durations
_REPLAY_DURATIONS = (30, 60)

# Max recent clips in tray menu
_MAX_RECENT = 3


class TrayIcon(QSystemTrayIcon):
    """System tray icon with dynamic context menu.

    Signals:
        show_requested: Emitted when the user left-clicks the tray icon.
        settings_requested: Emitted when Settings is chosen from the menu.
        quit_requested: Emitted when Quit is chosen from the menu.
        action_triggered(str): Emitted with an action name (e.g. ``"screenshot"``,
            ``"bookmark"``, ``"save_replay:30"``).
        recent_clicked(str): Emitted with a clip stem when a recent clip
            entry is clicked.
    """

    show_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    action_triggered = pyqtSignal(str)
    recent_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._icon = load_icon("moment", size=24)
        self.setIcon(self._icon)

        # Tooltip defaults
        self._status = "Idle"
        self._refresh_tooltip()

        # State
        self._recording = False  # whether gpu-screen-recorder is currently running
        self._recent_clips: list[tuple[str, str]] = []  # (stem, url) pairs

        # Build the initial menu
        self._menu: QMenu | None = None
        self._recent_menu: QMenu | None = None
        self._rebuild_menu()

        # Wire signals
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_status(self, status_text: str) -> None:
        """Update the tooltip and status-line menu item.

        Args:
            status_text: Human-readable status (e.g. ``"Encoding clip-1.mp4"``).
        """
        self._status = status_text
        self._refresh_tooltip()

        # Update the header item in the menu
        if self._menu is not None:
            header = self._menu.actions()[0] if self._menu.actions() else None
            if header is not None and not header.isSeparator():
                header.setText(f"Moment — {self._status}")

    def update_recent(self, clips: list[tuple[str, str]]) -> None:
        """Update the 'Replay recent' submenu with up-to-date clips.

        Args:
            clips: List of ``(stem, url)`` pairs, most recent first.
        """
        self._recent_clips = clips[:_MAX_RECENT]
        self._rebuild_recent_section()

    def set_recording(self, active: bool) -> None:
        """Enable or disable the replay / screenshot menu items.

        Args:
            active: ``True`` if gpu-screen-recorder is running.
        """
        self._recording = active
        if self._menu is not None:
            for action in self._menu.actions():
                name = action.property("action_name")
                if name in ("save_replay:30", "save_replay:60", "screenshot", "bookmark"):
                    action.setEnabled(active)

    # ------------------------------------------------------------------
    # Internal — menu construction
    # ------------------------------------------------------------------

    def _rebuild_menu(self) -> None:
        """(Re-)build the entire tray context menu."""
        menu = QMenu()
        menu.setMinimumWidth(220)

        # --- Header (disabled, shows status) ---
        header = QAction(f"Moment — {self._status}", menu)
        header.setEnabled(False)
        menu.addAction(header)

        menu.addSeparator()

        # --- Open Moment ---
        open_action = QAction("Open Moment", menu)
        open_action.triggered.connect(self.show_requested.emit)
        menu.addAction(open_action)

        menu.addSeparator()

        # --- Recording actions ---
        replay_30 = QAction("Save 30s Replay", menu)
        replay_30.setProperty("action_name", "save_replay:30")
        replay_30.setEnabled(self._recording)
        replay_30.triggered.connect(lambda: self.action_triggered.emit("save_replay:30"))
        menu.addAction(replay_30)

        replay_60 = QAction("Save 60s Replay", menu)
        replay_60.setProperty("action_name", "save_replay:60")
        replay_60.setEnabled(self._recording)
        replay_60.triggered.connect(lambda: self.action_triggered.emit("save_replay:60"))
        menu.addAction(replay_60)

        screenshot = QAction("Screenshot", menu)
        screenshot.setProperty("action_name", "screenshot")
        screenshot.setEnabled(self._recording)
        screenshot.triggered.connect(lambda: self.action_triggered.emit("screenshot"))
        menu.addAction(screenshot)

        bookmark = QAction("Bookmark", menu)
        bookmark.setProperty("action_name", "bookmark")
        bookmark.setEnabled(self._recording)
        bookmark.triggered.connect(lambda: self.action_triggered.emit("bookmark"))
        menu.addAction(bookmark)

        menu.addSeparator()

        # --- Recent clips submenu ---
        self._recent_menu = QMenu("Replay recent", menu)
        for stem, url in self._recent_clips:
            clip_action = QAction(stem, self._recent_menu)
            clip_action.triggered.connect(
                lambda checked, s=stem: self.recent_clicked.emit(s)  # noqa: B023
            )
            self._recent_menu.addAction(clip_action)
        if not self._recent_clips:
            no_recent = QAction("No recent clips", self._recent_menu)
            no_recent.setEnabled(False)
            self._recent_menu.addAction(no_recent)
        menu.addMenu(self._recent_menu)

        menu.addSeparator()

        # --- Settings + Quit ---
        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(self.settings_requested.emit)
        menu.addAction(settings_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        # Replace the old menu
        old_menu = self._menu
        self._menu = menu
        self.setContextMenu(menu)

        # Clean up old menu (prevent leak)
        if old_menu is not None:
            old_menu.deleteLater()

    def _rebuild_recent_section(self) -> None:
        """Update only the 'Replay recent' submenu without rebuilding the whole menu."""
        if self._recent_menu is None:
            return

        self._recent_menu.clear()

        for stem, url in self._recent_clips:
            clip_action = QAction(stem, self._recent_menu)
            clip_action.triggered.connect(
                lambda checked, s=stem: self.recent_clicked.emit(s)  # noqa: B023
            )
            self._recent_menu.addAction(clip_action)

        if not self._recent_clips:
            no_recent = QAction("No recent clips", self._recent_menu)
            no_recent.setEnabled(False)
            self._recent_menu.addAction(no_recent)

    # ------------------------------------------------------------------
    # Internal — tooltip
    # ------------------------------------------------------------------

    def _refresh_tooltip(self) -> None:
        """Update the tray tooltip to reflect the current status."""
        self.setToolTip(f"Moment — {self._status}")

    # ------------------------------------------------------------------
    # Internal — event handlers
    # ------------------------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (click) events."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Left-click → toggle window
            self.show_requested.emit()

        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            # Middle-click → copy last clip URL
            self.action_triggered.emit("copy_last_url")

        elif reason == QSystemTrayIcon.ActivationReason.Context:
            # Right-click → context menu (handled by Qt automatically)
            pass
