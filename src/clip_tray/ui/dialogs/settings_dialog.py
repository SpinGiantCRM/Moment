"""Settings dialog — tabbed configuration with immediate persistence.

Four tabs: General, Encoding, Notifications, Game Detection.
Settings are persisted to the ``settings`` table on tab switch
(no Apply button).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from clip_tray.core.config import Config

logger = logging.getLogger(__name__)

# Encoding presets
_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
_CODECS = ["h264_nvenc", "hevc_nvenc", "av1_nvenc"]
_AUDIO_CODECS = ["aac", "opus", "copy"]
_ENCODE_TIMINGS = ["immediately", "after_game", "when_idle"]
_GAME_EXIT_BEHAVIORS = ["open_editor", "prompt", "nothing"]
_REVIEW_SIZES = ["small", "medium", "large"]


class SettingsDialog(QDialog):
    """Tabbed settings dialog — saves on tab switch, no Apply button."""

    def __init__(self, config: "Config | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._dirty = False

        self.setWindowTitle("Settings")
        self.setMinimumSize(600, 480)

        # --- Tabs ---
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general_tab(), "General")
        self._tabs.addTab(self._build_encoding_tab(), "Encoding")
        self._tabs.addTab(self._build_notifications_tab(), "Notifications")
        self._tabs.addTab(self._build_game_tab(), "Game Detection")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # --- Bottom bar ---
        buttons = QDialogButtonBox()
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.setObjectName("danger")
        reset_btn.clicked.connect(self._on_reset_defaults)
        reset_db_btn = QPushButton("Reset Database")
        reset_db_btn.setObjectName("danger")
        reset_db_btn.clicked.connect(self._on_reset_database)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self._on_close)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(reset_btn)
        btn_layout.addWidget(reset_db_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addLayout(btn_layout)

        self._load_settings()

    # ==================================================================
    # Tab builders
    # ==================================================================

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Behaviour
        behaviour = QGroupBox("Behaviour")
        bf = QFormLayout(behaviour)
        self._autostart_cb = QCheckBox("Start automatically on login")
        bf.addRow(self._autostart_cb)
        self._minimize_tray_cb = QCheckBox("Minimize to tray on close")
        self._minimize_tray_cb.setChecked(True)
        bf.addRow(self._minimize_tray_cb)
        layout.addWidget(behaviour)

        # Encoding timing
        timing = QGroupBox("Encoding")
        tf = QFormLayout(timing)
        self._encode_timing_cb = QComboBox()
        self._encode_timing_cb.addItems(_ENCODE_TIMINGS)
        tf.addRow("Encode timing:", self._encode_timing_cb)
        layout.addWidget(timing)

        # Storage
        storage = QGroupBox("Storage")
        sf = QFormLayout(storage)
        self._storage_path_lbl = QLabel("~/Videos (default)")
        self._storage_path_lbl.setObjectName("muted")
        sf.addRow("Recordings:", self._storage_path_lbl)
        sf.addRow("Encoded:", QLabel("~/.local/share/clip-tray/encoded"))
        layout.addWidget(storage)

        layout.addStretch()
        return tab

    def _build_encoding_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb = QGroupBox("Video")
        gf = QFormLayout(gb)
        self._codec_cb = QComboBox()
        self._codec_cb.addItems(_CODECS)
        gf.addRow("Codec:", self._codec_cb)
        self._preset_cb = QComboBox()
        self._preset_cb.addItems(_PRESETS)
        self._preset_cb.setCurrentIndex(5)  # p6 default
        gf.addRow("Preset:", self._preset_cb)
        self._cq_slider = QSpinBox()
        self._cq_slider.setRange(0, 51)
        self._cq_slider.setValue(23)
        gf.addRow("CQ (quality):", self._cq_slider)
        self._bitrate_sb = QSpinBox()
        self._bitrate_sb.setRange(1, 200)
        self._bitrate_sb.setValue(12)
        self._bitrate_sb.setSuffix(" Mbps")
        gf.addRow("Bitrate:", self._bitrate_sb)
        layout.addWidget(gb)

        gb2 = QGroupBox("Audio")
        gf2 = QFormLayout(gb2)
        self._audio_codec_cb = QComboBox()
        self._audio_codec_cb.addItems(_AUDIO_CODECS)
        gf2.addRow("Codec:", self._audio_codec_cb)
        self._noise_supp_cb = QCheckBox("Apply RNNoise to microphone track")
        self._noise_supp_cb.setChecked(False)
        gf2.addRow(self._noise_supp_cb)
        layout.addWidget(gb2)

        layout.addStretch()
        return tab

    def _build_notifications_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb = QGroupBox("Toast Notifications")
        gf = QFormLayout(gb)
        self._toast_success_cb = QCheckBox("Success")
        self._toast_success_cb.setChecked(True)
        gf.addRow(self._toast_success_cb)
        self._toast_info_cb = QCheckBox("Info")
        self._toast_info_cb.setChecked(True)
        gf.addRow(self._toast_info_cb)
        self._toast_warning_cb = QCheckBox("Warning")
        self._toast_warning_cb.setChecked(True)
        gf.addRow(self._toast_warning_cb)
        self._toast_error_cb = QCheckBox("Error")
        self._toast_error_cb.setChecked(True)
        gf.addRow(self._toast_error_cb)
        layout.addWidget(gb)

        gb2 = QGroupBox("Other")
        gf2 = QFormLayout(gb2)
        self._review_card_cb = QCheckBox("Show review cards on capture")
        self._review_card_cb.setChecked(True)
        gf2.addRow(self._review_card_cb)
        self._sound_cb = QCheckBox("Play sounds for clip events")
        self._sound_cb.setChecked(False)
        gf2.addRow(self._sound_cb)
        layout.addWidget(gb2)

        layout.addStretch()
        return tab

    def _build_game_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb = QGroupBox("Detection")
        gf = QFormLayout(gb)
        self._auto_detect_cb = QCheckBox("Auto-detect games via /proc scan")
        self._auto_detect_cb.setChecked(True)
        gf.addRow(self._auto_detect_cb)
        self._process_list_edit = QLineEdit()
        self._process_list_edit.setPlaceholderText("cs2, r5apex.exe, ...")
        gf.addRow("Game processes:", self._process_list_edit)
        self._scan_interval_sb = QSpinBox()
        self._scan_interval_sb.setRange(1, 60)
        self._scan_interval_sb.setValue(3)
        self._scan_interval_sb.setSuffix(" s")
        gf.addRow("Scan interval:", self._scan_interval_sb)
        layout.addWidget(gb)

        gb2 = QGroupBox("Behaviour During Game")
        gf2 = QFormLayout(gb2)
        self._pause_encode_cb = QCheckBox("Pause encoding during games")
        self._pause_encode_cb.setChecked(True)
        gf2.addRow(self._pause_encode_cb)
        self._pause_thumbnail_cb = QCheckBox("Pause thumbnail generation during games")
        self._pause_thumbnail_cb.setChecked(True)
        gf2.addRow(self._pause_thumbnail_cb)
        self._minimize_during_game_cb = QCheckBox("Minimize window during games")
        self._minimize_during_game_cb.setChecked(True)
        gf2.addRow(self._minimize_during_game_cb)
        self._game_exit_cb = QComboBox()
        self._game_exit_cb.addItems(_GAME_EXIT_BEHAVIORS)
        gf2.addRow("On game exit:", self._game_exit_cb)
        layout.addWidget(gb2)

        layout.addStretch()
        return tab

    # ==================================================================
    # Persistence
    # ==================================================================

    def _load_settings(self) -> None:
        """Load settings from config if available."""
        if self._config is None:
            return
        self._autostart_cb.setChecked(
            self._config.get("autostart", False)
        )
        self._minimize_tray_cb.setChecked(
            self._config.get("minimize_to_tray", True)
        )
        timing = self._config.get("encode_timing", "after_game")
        idx = self._encode_timing_cb.findText(timing)
        if idx >= 0:
            self._encode_timing_cb.setCurrentIndex(idx)

    def _save_settings(self) -> None:
        """Persist all settings to config."""
        if self._config is None:
            return
        self._config.set("autostart", self._autostart_cb.isChecked())
        self._config.set("minimize_to_tray", self._minimize_tray_cb.isChecked())
        self._config.set("encode_timing", self._encode_timing_cb.currentText())
        self._config.set("codec", self._codec_cb.currentText())
        self._config.set("preset", self._preset_cb.currentText())
        self._config.set("cq", self._cq_slider.value())
        self._config.set("bitrate_mbps", self._bitrate_sb.value())
        self._config.set("audio_codec", self._audio_codec_cb.currentText())
        self._config.set("noise_suppression", self._noise_supp_cb.isChecked())
        self._config.set("toast_success", self._toast_success_cb.isChecked())
        self._config.set("toast_info", self._toast_info_cb.isChecked())
        self._config.set("toast_warning", self._toast_warning_cb.isChecked())
        self._config.set("toast_error", self._toast_error_cb.isChecked())
        self._config.set("review_cards", self._review_card_cb.isChecked())
        self._config.set("sounds", self._sound_cb.isChecked())
        self._config.set("auto_detect_games", self._auto_detect_cb.isChecked())
        self._config.set("game_processes", self._process_list_edit.text())
        self._config.set("game_scan_interval", self._scan_interval_sb.value())
        self._config.set("pause_encode_during_game", self._pause_encode_cb.isChecked())
        self._config.set("pause_thumbnail_during_game", self._pause_thumbnail_cb.isChecked())
        self._config.set("minimize_during_game", self._minimize_during_game_cb.isChecked())
        self._config.set("game_exit_behavior", self._game_exit_cb.currentText())

    # ==================================================================
    # Handlers
    # ==================================================================

    def _on_tab_changed(self, index: int) -> None:
        """Save settings when switching tabs."""
        self._save_settings()

    def _on_close(self) -> None:
        """Save and close."""
        self._save_settings()
        self.accept()

    def _on_reset_defaults(self) -> None:
        """Confirm and reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset Defaults",
            "Reset all settings to their default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Reset checkboxes
        for cb in [
            self._autostart_cb, self._minimize_tray_cb,
            self._noise_supp_cb, self._toast_success_cb, self._toast_info_cb,
            self._toast_warning_cb, self._toast_error_cb, self._review_card_cb,
            self._sound_cb, self._auto_detect_cb,
            self._pause_encode_cb, self._pause_thumbnail_cb,
            self._minimize_during_game_cb,
        ]:
            cb.setChecked(True)
        self._autostart_cb.setChecked(False)
        self._noise_supp_cb.setChecked(False)
        self._sound_cb.setChecked(False)
        self._encode_timing_cb.setCurrentIndex(1)  # after_game
        self._codec_cb.setCurrentIndex(0)
        self._preset_cb.setCurrentIndex(5)
        self._cq_slider.setValue(23)
        self._bitrate_sb.setValue(12)
        self._audio_codec_cb.setCurrentIndex(0)
        self._process_list_edit.clear()
        self._scan_interval_sb.setValue(3)
        self._game_exit_cb.setCurrentIndex(0)
        self._save_settings()
        logger.info("Settings reset to defaults")

    def _on_reset_database(self) -> None:
        """Confirm and reset (delete) the database."""
        reply = QMessageBox.critical(
            self,
            "Reset Database",
            "This will permanently delete ALL clips, tags, profiles, "
            "and settings from the database.\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import os
        db_path = os.path.expanduser("~/.config/clip-tray/clips.db")
        try:
            os.unlink(db_path)
            QMessageBox.information(
                self, "Database Reset",
                "Database deleted. Restart clip-tray to recreate it."
            )
        except FileNotFoundError:
            QMessageBox.information(
                self, "Database Reset",
                "No database found to delete."
            )
        except OSError as exc:
            QMessageBox.warning(
                self, "Database Reset",
                f"Could not delete database: {exc}"
            )
