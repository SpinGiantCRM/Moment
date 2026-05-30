"""Game profile dialog — per-game recording configuration.

Displays a list of game profiles on the left and an inline editing
panel on the right.  Profiles are persisted through the Store.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from moment.core.models import GameProfile, ReviewCardConfig

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

_REVIEW_SIZES = ["small", "medium", "large"]


class GameProfileDialog(QDialog):
    """Per-game capture settings editor."""

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._profiles: list[GameProfile] = []
        self._current_idx: int = -1

        self.setWindowTitle("Game Profiles")
        self.setMinimumSize(700, 500)
        self.setModal(True)

        # --- Profile list (left) ---
        left = QVBoxLayout()

        self._profile_list = QListWidget()
        self._profile_list.setFixedWidth(200)
        self._profile_list.currentRowChanged.connect(self._on_profile_selected)
        left.addWidget(self._profile_list)

        list_btns = QHBoxLayout()
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(32)
        add_btn.clicked.connect(self._add_profile)
        list_btns.addWidget(add_btn)
        rem_btn = QPushButton("−")
        rem_btn.setFixedWidth(32)
        rem_btn.clicked.connect(self._remove_profile)
        list_btns.addWidget(rem_btn)
        list_btns.addStretch()
        left.addLayout(list_btns)

        # --- Editing panel (right) ---
        right = QWidget()
        rf = QFormLayout(right)

        # Profile info
        info_gb = QGroupBox("Profile")
        info_f = QFormLayout(info_gb)
        self._binary_edit = QLineEdit()
        self._binary_edit.setPlaceholderText("cs2")
        info_f.addRow("Binary name:", self._binary_edit)
        self._display_edit = QLineEdit()
        self._display_edit.setPlaceholderText("Counter-Strike 2")
        info_f.addRow("Display name:", self._display_edit)
        rf.addWidget(info_gb)

        # Capture
        cap_gb = QGroupBox("Capture")
        cap_f = QFormLayout(cap_gb)
        self._replay_sb = QSpinBox()
        self._replay_sb.setRange(5, 600)
        self._replay_sb.setValue(30)
        self._replay_sb.setSuffix(" s")
        cap_f.addRow("Replay duration:", self._replay_sb)
        self._fps_sb = QSpinBox()
        self._fps_sb.setRange(15, 240)
        self._fps_sb.setValue(60)
        cap_f.addRow("Capture FPS:", self._fps_sb)
        self._encode_timing_cb = QComboBox()
        self._encode_timing_cb.addItems(["inherit", "immediately", "after_game", "when_idle"])
        cap_f.addRow("Encode timing:", self._encode_timing_cb)
        self._quality_slider = QSpinBox()
        self._quality_slider.setRange(10, 51)
        self._quality_slider.setValue(23)
        self._quality_slider.setSuffix(" CQ")
        cap_f.addRow("Quality:", self._quality_slider)
        rf.addWidget(cap_gb)

        # Behaviour
        beh_gb = QGroupBox("Behaviour")
        beh_f = QFormLayout(beh_gb)
        self._pause_encode_cb = QCheckBox()
        self._pause_encode_cb.setChecked(True)
        beh_f.addRow("Pause encode:", self._pause_encode_cb)
        self._pause_thumb_cb = QCheckBox()
        self._pause_thumb_cb.setChecked(True)
        beh_f.addRow("Pause thumbnails:", self._pause_thumb_cb)
        self._auto_tag_edit = QLineEdit()
        self._auto_tag_edit.setPlaceholderText("auto-tag name")
        beh_f.addRow("Auto-tag:", self._auto_tag_edit)
        self._auto_open_cb = QCheckBox()
        self._auto_open_cb.setChecked(True)
        beh_f.addRow("Auto-open editor:", self._auto_open_cb)
        rf.addWidget(beh_gb)

        # Review card
        rc_gb = QGroupBox("Review Card")
        rc_f = QFormLayout(rc_gb)
        self._review_size_cb = QComboBox()
        self._review_size_cb.addItems(_REVIEW_SIZES)
        self._review_size_cb.setCurrentIndex(1)
        rc_f.addRow("Card size:", self._review_size_cb)
        rf.addWidget(rc_gb)

        # --- Main layout ---
        content = QHBoxLayout()
        content.addLayout(left)
        content.addWidget(right)

        # --- Bottom buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        delete_btn = QPushButton("Delete Profile")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete_current)
        btn_layout.addWidget(delete_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(content)
        layout.addLayout(btn_layout)

        # Load existing profiles
        self._load_profiles()

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def _load_profiles(self) -> None:
        """Load profiles from the store."""
        if self._store is None:
            return
        self._profiles = self._store.list_game_profiles()
        self._profile_list.clear()
        for p in self._profiles:
            item = QListWidgetItem(p.display_name or p.game_name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self._profile_list.addItem(item)

    def _add_profile(self) -> None:
        """Create a new blank profile."""
        profile = GameProfile(
            id=str(uuid.uuid4()),
            game_name="",
            display_name="New Game",
        )
        self._profiles.append(profile)
        item = QListWidgetItem(profile.display_name)
        item.setData(Qt.ItemDataRole.UserRole, profile.id)
        self._profile_list.addItem(item)
        self._profile_list.setCurrentRow(len(self._profiles) - 1)
        self._binary_edit.setFocus()

    def _remove_profile(self) -> None:
        """Remove the selected profile from the list."""
        row = self._profile_list.currentRow()
        if row < 0:
            return
        self._profile_list.takeItem(row)
        del self._profiles[row]

    def _delete_current(self) -> None:
        """Delete the current profile from the store."""
        row = self._profile_list.currentRow()
        if row < 0:
            return
        profile = self._profiles[row]
        if self._store:
            self._store.delete_game_profile(profile.game_name)
        self._profile_list.takeItem(row)
        del self._profiles[row]
        self._clear_fields()

    def _on_profile_selected(self, row: int) -> None:
        """Load the selected profile into the editing panel."""
        if row < 0 or row >= len(self._profiles):
            self._clear_fields()
            return
        p = self._profiles[row]
        self._binary_edit.setText(p.game_name)
        self._display_edit.setText(p.display_name)
        self._replay_sb.setValue(p.replay_duration)
        self._fps_sb.setValue(p.capture_fps)
        idx = self._encode_timing_cb.findText(p.encode_timing or "inherit")
        self._encode_timing_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._quality_slider.setValue(int(p.quality_preset or 23))
        self._pause_encode_cb.setChecked(p.pause_encode)
        self._pause_thumb_cb.setChecked(p.pause_thumbnail)
        self._auto_tag_edit.setText(p.game_name if p.auto_tag else "")
        self._auto_open_cb.setChecked(p.auto_open_editor)
        if p.review_card:
            idx = self._review_size_cb.findText(p.review_card.size)
            self._review_size_cb.setCurrentIndex(idx if idx >= 0 else 1)

    def _clear_fields(self) -> None:
        """Clear the editing panel."""
        self._binary_edit.clear()
        self._display_edit.clear()
        self._replay_sb.setValue(30)
        self._fps_sb.setValue(60)
        self._encode_timing_cb.setCurrentIndex(0)
        self._quality_slider.setValue(23)
        self._pause_encode_cb.setChecked(True)
        self._pause_thumb_cb.setChecked(True)
        self._auto_tag_edit.clear()
        self._auto_open_cb.setChecked(True)
        self._review_size_cb.setCurrentIndex(1)

    def _save_and_close(self) -> None:
        """Save all profiles to the store and close."""
        if self._store is None:
            self.accept()
            return

        for profile in self._profiles:
            self._store.save_game_profile(profile)

        # Apply current edits to selected profile
        row = self._profile_list.currentRow()
        if 0 <= row < len(self._profiles):
            p = self._profiles[row]
            p.game_name = self._binary_edit.text().strip()
            p.display_name = self._display_edit.text().strip() or p.game_name
            p.replay_duration = self._replay_sb.value()
            p.capture_fps = self._fps_sb.value()
            timing = self._encode_timing_cb.currentText()
            p.encode_timing = timing if timing != "inherit" else None
            p.quality_preset = str(self._quality_slider.value())
            p.pause_encode = self._pause_encode_cb.isChecked()
            p.pause_thumbnail = self._pause_thumb_cb.isChecked()
            p.auto_tag = bool(self._auto_tag_edit.text().strip())
            p.auto_open_editor = self._auto_open_cb.isChecked()
            p.review_card = ReviewCardConfig(
                size=self._review_size_cb.currentText(),
            )
            self._store.save_game_profile(p)

            # Update list item name
            item = self._profile_list.item(row)
            if item:
                item.setText(p.display_name)

        self.accept()
