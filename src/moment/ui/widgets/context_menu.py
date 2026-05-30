"""Context menu — builder for right-click clip menus.

Constructs a QMenu with all clip actions.  The menu structure mirrors the
spec — copy URL, rename, open folders, re-encode, favorites, tags, delete,
and a "Select" action for batch mode.

Usage::

    builder = ContextMenuBuilder(clip=clip)
    menu = builder.build()
    action = menu.exec(event.globalPos())
    # Connect to builder's signals to handle actions:
    builder.copy_url_triggered.connect(handler)
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenu

from moment.core.models import Clip
from moment.ui.resources import color


class ContextMenuBuilder:
    """Builds a right-click context menu for a clip."""

    # Signals — emitted when actions are triggered
    copy_url_triggered = pyqtSignal(str)  # clip_id
    rename_triggered = pyqtSignal(str)
    open_source_triggered = pyqtSignal(str)
    open_encoded_triggered = pyqtSignal(str)
    open_player_triggered = pyqtSignal(str)
    reencode_triggered = pyqtSignal(str)
    reupload_triggered = pyqtSignal(str)
    favorite_triggered = pyqtSignal(str)
    manage_tags_triggered = pyqtSignal(str)
    set_game_triggered = pyqtSignal(str)
    protect_triggered = pyqtSignal(str)
    delete_triggered = pyqtSignal(str)
    select_triggered = pyqtSignal(str)

    def __init__(self, clip: Clip, parent: object | None = None) -> None:
        self._clip = clip
        self._parent = parent

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> QMenu:
        """Construct and return the fully populated QMenu."""
        menu = QMenu(self._parent)
        menu.setStyleSheet(self._menu_style())

        # --- Row 1: Copy URL, Rename ---
        copy_action = self._add_action(menu, "Copy URL", "Ctrl+C")
        copy_action.triggered.connect(lambda: self.copy_url_triggered.emit(self._clip.id))

        rename_action = self._add_action(menu, "Rename", "F2")
        rename_action.triggered.connect(lambda: self.rename_triggered.emit(self._clip.id))

        menu.addSeparator()

        # --- Row 2: Open folders ---
        open_src = self._add_action(menu, "Open Source Folder")
        open_src.triggered.connect(lambda: self.open_source_triggered.emit(self._clip.id))

        open_enc = self._add_action(menu, "Open Encoded Folder")
        open_enc.setEnabled(self._clip.encoded_path is not None)
        open_enc.triggered.connect(lambda: self.open_encoded_triggered.emit(self._clip.id))

        open_player = self._add_action(menu, "Open in Player")
        open_player.triggered.connect(lambda: self.open_player_triggered.emit(self._clip.id))

        menu.addSeparator()

        # --- Row 3: Re-encode / Re-upload ---
        reencode = self._add_action(menu, "Re-encode")
        reencode.triggered.connect(lambda: self.reencode_triggered.emit(self._clip.id))

        reupload = self._add_action(menu, "Re-upload")
        reupload.setEnabled(self._clip.r2_url is not None)
        reupload.triggered.connect(lambda: self.reupload_triggered.emit(self._clip.id))

        menu.addSeparator()

        # --- Row 4: Favorite, Tags, Game ---
        fav_text = "★ Unfavorite" if self._clip.favorite else "☆ Toggle Favorite"
        fav_action = self._add_action(menu, fav_text)
        fav_action.triggered.connect(lambda: self.favorite_triggered.emit(self._clip.id))

        tags_action = self._add_action(menu, "Manage Tags")
        tags_action.triggered.connect(lambda: self.manage_tags_triggered.emit(self._clip.id))

        game_action = self._add_action(menu, "Set Game")
        game_action.triggered.connect(lambda: self.set_game_triggered.emit(self._clip.id))

        menu.addSeparator()

        # --- Row 5: Protect, Delete ---
        protect_text = "🔒 Unprotect" if self._clip.protect_from_retention else "Protect from Retention"
        protect_action = self._add_action(menu, protect_text)
        protect_action.triggered.connect(lambda: self.protect_triggered.emit(self._clip.id))

        delete_action = self._add_action(menu, "Delete", "Del")
        delete_action.triggered.connect(lambda: self.delete_triggered.emit(self._clip.id))

        menu.addSeparator()

        # --- Row 6: Select ---
        select_action = self._add_action(menu, "Select")
        select_action.triggered.connect(lambda: self.select_triggered.emit(self._clip.id))

        return menu

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_action(menu: QMenu, text: str, shortcut: str | None = None) -> QAction:
        action = QAction(text, menu)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        menu.addAction(action)
        return action

    @staticmethod
    def _menu_style() -> str:
        return f"""
            QMenu {{
                background-color: {color('--bg-surface')};
                color: {color('--text-primary')};
                border: 1px solid {color('--border-menu')};
                border-radius: 6px;
                padding: 4px 0;
                font-size: 13px;
            }}
            QMenu::item {{
                padding: 6px 28px 6px 12px;
            }}
            QMenu::item:selected {{
                background-color: {color('--bg-elevated')};
            }}
            QMenu::item:disabled {{
                color: {color('--text-muted')};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {color('--border-menu')};
                margin: 4px 8px;
            }}
        """
