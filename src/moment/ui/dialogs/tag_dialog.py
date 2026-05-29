"""Tag dialog — manage tags for one or more clips.

Lists existing tags with remove buttons and provides an autocomplete
input for adding new tags.  Works in single-clip and batch modes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QStringListModel
from PyQt6.QtWidgets import (
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class TagDialog(QDialog):
    """Tag management dialog with autocomplete.

    Args:
        current_tags: Tags already applied to the clip(s).
        all_tags: All known tags in the system (for autocomplete).
        batch_count: If > 1, shows a batch-mode label.
        store: Store instance for persisting changes (optional).
    """

    def __init__(
        self,
        current_tags: list[str] | None = None,
        all_tags: list[str] | None = None,
        batch_count: int = 1,
        store: "Store | None" = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._batch_count = max(batch_count, 1)
        self._all_tags = all_tags or []

        self.setWindowTitle("Manage Tags")
        self.setMinimumSize(350, 320)
        self.setModal(True)

        # --- Batch label ---
        if self._batch_count > 1:
            batch_label = QLabel(f"Editing tags for {self._batch_count} clips")
            batch_label.setObjectName("cardMeta")

        # --- Tag list ---
        self._tag_list = QListWidget()
        self._tag_list.setSpacing(2)
        self._tag_list.setAlternatingRowColors(False)

        for tag in (current_tags or []):
            self._add_tag_row(tag)

        # --- Add tag input ---
        add_layout = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("Add tag…")
        self._add_input.returnPressed.connect(self._add_tag)

        # Autocomplete from existing tags
        completer = QCompleter(self._all_tags)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer_model = QStringListModel(self._all_tags)
        completer.setModel(completer_model)
        self._add_input.setCompleter(completer)

        add_btn = QPushButton("+")
        add_btn.setFixedWidth(32)
        add_btn.clicked.connect(self._add_tag)
        add_layout.addWidget(self._add_input)
        add_layout.addWidget(add_btn)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("accent")
        apply_btn.clicked.connect(self.accept)
        btn_layout.addWidget(apply_btn)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        if self._batch_count > 1:
            layout.addWidget(batch_label)
        layout.addWidget(QLabel("Current tags:"))
        layout.addWidget(self._tag_list)
        layout.addLayout(add_layout)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Tag operations
    # ------------------------------------------------------------------

    def _add_tag_row(self, name: str) -> None:
        """Add a tag row with remove button to the list."""
        item = QListWidgetItem()
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)

        label = QLabel(name)
        layout.addWidget(label)

        remove_btn = QPushButton("×")
        remove_btn.setFixedSize(20, 20)
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(
            lambda checked, n=name: self._remove_tag(n)
        )
        layout.addWidget(remove_btn)
        layout.addStretch()

        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setSizeHint(widget.sizeHint())
        self._tag_list.addItem(item)
        self._tag_list.setItemWidget(item, widget)

    def _add_tag(self) -> None:
        """Add the tag from the input field."""
        name = self._add_input.text().strip()
        if not name:
            return
        # Check for duplicates
        for i in range(self._tag_list.count()):
            existing = self._tag_list.item(i)
            if existing and existing.data(Qt.ItemDataRole.UserRole) == name:
                self._add_input.clear()
                return

        self._add_tag_row(name)
        self._add_input.clear()

        # Add to known tags for future autocomplete
        if name not in self._all_tags:
            self._all_tags.append(name)
            self._add_input.completer().model().setStringList(self._all_tags)

    def _remove_tag(self, name: str) -> None:
        """Remove a tag row by name."""
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == name:
                self._tag_list.takeItem(i)
                break

    # ------------------------------------------------------------------
    # Result access
    # ------------------------------------------------------------------

    def get_tags(self) -> list[str]:
        """Return the final list of tags."""
        tags: list[str] = []
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item:
                name = item.data(Qt.ItemDataRole.UserRole)
                if name:
                    tags.append(name)
        return tags
