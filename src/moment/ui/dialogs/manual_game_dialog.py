"""Manual game dialog — add game process names to bypass auto-detection.

Useful on Wayland / Flatpak where auto-detection may be limited.
Opened from the Recording page's "Configure Games" button.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from moment.core.game_profiles import GameProfileManager
from moment.ui.base_dialog import ThemedDialog

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class ManualGameDialog(ThemedDialog):
    """Simple dialog for manually adding game process names.

    The user types a process name (e.g. ``"eldenring.exe"`` via Proton)
    and it's saved to game profiles, bypassing auto-detection entirely.
    """

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._mgr = GameProfileManager(store) if store else None

        self.setWindowTitle("Configure Games")
        self.setMinimumSize(400, 320)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(
            "Add game process names manually.\n"
            "Useful when auto-detection is unavailable (Flatpak, Wayland)."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        layout.addWidget(header)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. eldenring.exe, cs2, hl2_linux")
        self._name_input.returnPressed.connect(self._add_current)
        input_row.addWidget(self._name_input, 1)

        add_btn = QPushButton("Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_current)
        input_row.addWidget(add_btn)

        layout.addLayout(input_row)

        # List of current binaries
        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        # Remove button
        remove_row = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        remove_row.addWidget(remove_btn)
        remove_row.addStretch()
        layout.addLayout(remove_row)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        # Load existing profiles
        self._load_existing()

    def _load_existing(self) -> None:
        """Load existing game profiles into the list."""
        if self._mgr is None:
            return
        self._list.clear()
        for profile in self._mgr.list():
            item = QListWidgetItem(profile.game_name)
            item.setData(Qt.ItemDataRole.UserRole, profile.game_name)
            self._list.addItem(item)

    def _add_current(self) -> None:
        """Add the current input text as a game profile."""
        name = self._name_input.text().strip()
        if not name:
            return
        if self._mgr is None:
            return

        # Check for duplicates
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.text() == name:
                logger.debug("Game '%s' already in list, skipping", name)
                self._name_input.clear()
                return

        try:
            profile = self._mgr.create_default(name)
            self._mgr.save(profile)
            logger.info("Manually added game: %s", name)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)
            self._name_input.clear()
        except Exception as exc:
            logger.warning("Failed to add game '%s': %s", name, exc)

    def _remove_selected(self) -> None:
        """Remove the selected game profile."""
        row = self._list.currentRow()
        if row < 0:
            return
        item = self._list.item(row)
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole) or item.text()

        if self._mgr is not None:
            try:
                self._mgr.delete(name)
                logger.info("Removed game: %s", name)
            except Exception as exc:
                logger.warning("Failed to remove game '%s': %s", name, exc)

        self._list.takeItem(row)
