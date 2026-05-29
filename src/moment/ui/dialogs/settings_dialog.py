"""Settings dialog — tabbed configuration with immediate persistence.

Tabs: General, Encoding, Notifications, Game Detection,
Recording, Storage Locations.
Settings are persisted to the ``settings`` table on tab switch
(no Apply button).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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
    from moment.core.config import Config

from moment.core.config import _PATH_DEFAULTS

# Resolve palette colours for the Appearance tab (with fallback)
try:
    from moment.ui.resources import color as _palette_color
except ImportError:
    _palette_color = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Encoding presets
_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
_AUDIO_CODECS = ["aac", "opus", "copy"]

# Video encoder dropdown — label → ffmpeg encoder name
_VIDEO_ENCODER_OPTIONS: list[tuple[str, str]] = [
    ("Auto (detect best)", "auto"),
    ("NVENC H.264", "h264_nvenc"),
    ("NVENC HEVC", "hevc_nvenc"),
    ("NVENC AV1", "av1_nvenc"),
    ("VAAPI H.264", "h264_vaapi"),
    ("VAAPI HEVC", "hevc_vaapi"),
    ("VAAPI AV1", "av1_vaapi"),
    ("QSV H.264", "h264_qsv"),
    ("QSV HEVC", "hevc_qsv"),
    ("QSV AV1", "av1_qsv"),
    ("Software (libx264)", "libx264"),
]
_ENCODE_TIMINGS = ["immediately", "after_game", "when_idle"]
_GAME_EXIT_BEHAVIORS = ["open_editor", "prompt", "nothing"]
_REVIEW_SIZES = ["small", "medium", "large"]

# Appearance tab swatches: (label, token, fallback_hex)
_APPEARANCE_SWATCHES: list[tuple[str, str, str]] = [
    ("Window BG", "--bg-window", "#3c3c3c"),
    ("Surface", "--bg-surface", "#333333"),
    ("Elevated", "--bg-elevated", "#404040"),
    ("Inset", "--bg-inset", "#2a2a2a"),
    ("Primary Text", "--text-primary", "#d9d9d9"),
    ("Secondary", "--text-secondary", "#a1a1aa"),
    ("Accent Blue", "--accent-blue", "#60a5fa"),
    ("Accent Red", "--accent-red", "#f87171"),
    ("Accent Green", "--accent-green", "#4ade80"),
]


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
        self._tabs.addTab(self._build_recording_tab(), "Recording")
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_storage_tab(), "Storage Locations")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # --- Bottom bar ---
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
        sf.addRow("Encoded:", QLabel("~/.local/share/moment/encoded"))
        layout.addWidget(storage)

        layout.addStretch()
        return tab

    def _build_encoding_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Video encoder
        encoder_gb = QGroupBox("Video Encoder")
        ef = QFormLayout(encoder_gb)
        self._video_encoder_cb = QComboBox()
        self._video_encoder_cb.addItems(
            [label for label, _ in _VIDEO_ENCODER_OPTIONS]
        )
        ef.addRow("Video codec:", self._video_encoder_cb)
        layout.addWidget(encoder_gb)

        gb = QGroupBox("Video")
        gf = QFormLayout(gb)

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

    def _build_recording_tab(self) -> QWidget:
        """Recording tab — GSR instant-replay settings."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Mode
        mode_gb = QGroupBox("Recording Mode")
        mf = QFormLayout(mode_gb)
        self._replay_enabled_cb = QCheckBox(
            "Enable instant replay (gpu-screen-recorder -k)"
        )
        self._replay_enabled_cb.setToolTip(
            "When enabled, Moment launches gpu-screen-recorder in "
            "headless replay-buffer mode at startup. The overlay "
            "hotkey (Alt+Z) saves the last N seconds of gameplay."
        )
        mf.addRow(self._replay_enabled_cb)
        layout.addWidget(mode_gb)

        # Capture settings
        capture_gb = QGroupBox("Capture")
        cf = QFormLayout(capture_gb)

        self._replay_fps_sb = QSpinBox()
        self._replay_fps_sb.setRange(15, 240)
        self._replay_fps_sb.setValue(60)
        self._replay_fps_sb.setSuffix(" fps")
        cf.addRow("Frame rate:", self._replay_fps_sb)

        self._replay_quality_cb = QComboBox()
        self._replay_quality_cb.addItems(
            ["ultra_fast", "very_fast", "fast", "medium",
             "slow", "very_high", "high"]
        )
        self._replay_quality_cb.setCurrentText("very_high")
        cf.addRow("Quality:", self._replay_quality_cb)

        self._replay_container_cb = QComboBox()
        self._replay_container_cb.addItems(["mp4", "mkv", "flv"])
        cf.addRow("Container:", self._replay_container_cb)

        self._replay_codec_edit = QLineEdit()
        self._replay_codec_edit.setPlaceholderText("auto (h264_nvenc, hevc_nvenc, …)")
        cf.addRow("Video codec:", self._replay_codec_edit)

        self._replay_duration_sb = QSpinBox()
        self._replay_duration_sb.setRange(30, 600)
        self._replay_duration_sb.setValue(120)
        self._replay_duration_sb.setSuffix(" s")
        self._replay_duration_sb.setToolTip("Circular buffer size in seconds")
        cf.addRow("Buffer duration:", self._replay_duration_sb)

        self._replay_audio_edit = QLineEdit()
        self._replay_audio_edit.setPlaceholderText("default_output (leave empty to disable)")
        cf.addRow("Audio device:", self._replay_audio_edit)

        self._replay_area_cb = QComboBox()
        self._replay_area_cb.addItems(["screen", "focused", "window"])
        cf.addRow("Record area:", self._replay_area_cb)

        self._replay_show_cursor_cb = QCheckBox("Show cursor in recordings")
        self._replay_show_cursor_cb.setChecked(True)
        cf.addRow(self._replay_show_cursor_cb)

        layout.addWidget(capture_gb)

        # Overlay
        overlay_gb = QGroupBox("Overlay")
        of = QFormLayout(overlay_gb)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("Alt+Z")
        self._hotkey_edit.setToolTip(
            "Global hotkey to show/hide the overlay. "
            "On KDE, this intercepts GSR's built-in hotkey."
        )
        of.addRow("Save hotkey:", self._hotkey_edit)

        self._overlay_auto_hide_sb = QSpinBox()
        self._overlay_auto_hide_sb.setRange(4, 15)
        self._overlay_auto_hide_sb.setValue(8)
        self._overlay_auto_hide_sb.setSuffix(" s")
        self._overlay_auto_hide_sb.setToolTip(
            "Seconds of inactivity before the overlay auto-hides"
        )
        of.addRow("Auto-hide:", self._overlay_auto_hide_sb)

        layout.addWidget(overlay_gb)

        layout.addStretch()
        return tab

    def _build_appearance_tab(self) -> QWidget:
        """Appearance tab — live color swatches showing the Moment palette."""
        # Resolve palette from resources if available, else fall back to hex
        if _palette_color is not None:
            _swatch_colors: dict[str, str] = {
                name: _palette_color(token)
                for name, token, _hex in _APPEARANCE_SWATCHES
            }
        else:
            _swatch_colors = {}

        tab = QWidget()
        layout = QVBoxLayout(tab)

        gb = QGroupBox("Theme Palette")
        gb_layout = QVBoxLayout(gb)
        gb_layout.setSpacing(8)

        desc = QLabel(
            "Moment uses a dark palette. Below are the current theme colors.\n"
            "Theme switching (light/dark) is planned for a future release."
        )
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        gb_layout.addWidget(desc)

        # Color swatches grid
        swatch_grid = QHBoxLayout()
        swatch_grid.setSpacing(6)

        for label, token, fallback_hex in _APPEARANCE_SWATCHES:
            hex_val = _swatch_colors.get(label, fallback_hex)
            swatch_widget = QWidget()
            swatch_widget.setFixedSize(64, 64)
            swatch_layout = QVBoxLayout(swatch_widget)
            swatch_layout.setContentsMargins(0, 0, 0, 0)
            swatch_layout.setSpacing(4)

            swatch = QLabel()
            swatch.setFixedSize(48, 48)
            swatch.setStyleSheet(
                f"background-color: {hex_val};"
                "border-radius: 8px;"
                "border: 1px solid var(--bg-hover);"
            )
            swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            swatch_layout.addWidget(swatch, alignment=Qt.AlignmentFlag.AlignCenter)

            swatch_label = QLabel(label)
            swatch_label.setObjectName("cardMeta")
            swatch_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            swatch_label.setStyleSheet("font-size: 10px;")
            swatch_layout.addWidget(swatch_label)

            swatch_grid.addWidget(swatch_widget)

        gb_layout.addLayout(swatch_grid)

        # Theme note
        theme_note = QLabel(
            "Custom themes, font scaling, and accent color overrides are coming soon."
        )
        theme_note.setObjectName("muted")
        theme_note.setWordWrap(True)
        gb_layout.addWidget(theme_note)

        layout.addWidget(gb)
        layout.addStretch()
        return tab

    def _build_storage_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Path fields: (key, label, is_directory)
        self._storage_fields: dict[str, QLineEdit] = {}
        path_fields: list[tuple[str, str]] = [
            ("db_dir", "Database directory"),
            ("data_dir", "Data directory"),
            ("encode_dir", "Encode output"),
            ("thumb_dir", "Thumbnail cache"),
            ("temp_dir", "Temporary files"),
            ("log_dir", "Log directory"),
            ("recordings_dir", "Recordings (source)"),
        ]

        gb_paths = QGroupBox("Storage Paths")
        pf = QFormLayout(gb_paths)
        for key, label in path_fields:
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setPlaceholderText(self._get_path_default(key))
            self._storage_fields[key] = edit
            row.addWidget(edit, 1)
            browse_btn = QPushButton("Browse…")
            browse_btn.clicked.connect(lambda checked, k=key: self._on_browse_path(k))
            row.addWidget(browse_btn)
            pf.addRow(f"{label}:", row)
        layout.addWidget(gb_paths)

        # Non-path fields
        gb_rclone = QGroupBox("Cloud Storage")
        rf = QFormLayout(gb_rclone)

        self._rclone_remote_edit = QLineEdit()
        self._rclone_remote_edit.setPlaceholderText(self._get_path_default("rclone_remote"))
        rf.addRow("Rclone remote:", self._rclone_remote_edit)

        self._rclone_bucket_edit = QLineEdit()
        self._rclone_bucket_edit.setPlaceholderText(self._get_path_default("rclone_bucket"))
        rf.addRow("Rclone bucket:", self._rclone_bucket_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("(empty)")
        rf.addRow("Base URL:", self._base_url_edit)
        layout.addWidget(gb_rclone)

        # Reset button
        reset_btn = QPushButton("Reset Storage to Defaults")
        reset_btn.clicked.connect(self._on_reset_storage)
        layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addStretch()
        return tab

    @staticmethod
    def _get_path_default(key: str) -> str:
        """Return a human-readable default for display in placeholder text."""
        val = _PATH_DEFAULTS.get(key, "")
        if val and key not in ("rclone_remote", "rclone_bucket", "base_url"):
            val = os.path.expanduser(val)
        return val

    def _on_browse_path(self, key: str) -> None:
        """Open a directory picker for a storage path field."""
        current = self._storage_fields[key].text() or self._get_path_default(key)
        directory = QFileDialog.getExistingDirectory(self, f"Select {key}", current)
        if directory:
            self._storage_fields[key].setText(directory)

    def _on_reset_storage(self) -> None:
        """Clear all storage path overrides."""
        reply = QMessageBox.question(
            self,
            "Reset Storage",
            "Reset all storage paths to their default locations?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for edit in self._storage_fields.values():
            edit.clear()
        self._rclone_remote_edit.clear()
        self._rclone_bucket_edit.clear()
        self._base_url_edit.clear()
        if self._config is not None:
            self._config.reset_paths()
        logger.info("Storage paths reset to defaults")

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

        # Load encoding settings
        preferred_codec = self._config.get_preferred_codec()
        for i, (label, value) in enumerate(_VIDEO_ENCODER_OPTIONS):
            if value == preferred_codec:
                self._video_encoder_cb.setCurrentIndex(i)
                break
        preset = self._config.get("preset", "p6")
        idx = self._preset_cb.findText(str(preset))
        if idx >= 0:
            self._preset_cb.setCurrentIndex(idx)
        self._cq_slider.setValue(self._config.get("cq", 23))
        self._bitrate_sb.setValue(self._config.get("bitrate_mbps", 12))
        audio = self._config.get("audio_codec", "aac")
        idx = self._audio_codec_cb.findText(str(audio))
        if idx >= 0:
            self._audio_codec_cb.setCurrentIndex(idx)
        self._noise_supp_cb.setChecked(
            self._config.get("noise_suppression", False)
        )

        # Load recording settings
        self._replay_enabled_cb.setChecked(
            self._config.get_gsr_setting("replay_enabled") is True
        )
        replay_fps = self._config.get_gsr_setting("replay_fps")
        if isinstance(replay_fps, int):
            self._replay_fps_sb.setValue(replay_fps)
        replay_quality = self._config.get_gsr_setting("replay_quality")
        if isinstance(replay_quality, str):
            idx = self._replay_quality_cb.findText(replay_quality)
            if idx >= 0:
                self._replay_quality_cb.setCurrentIndex(idx)
        replay_container = self._config.get_gsr_setting("replay_container")
        if isinstance(replay_container, str):
            idx = self._replay_container_cb.findText(replay_container)
            if idx >= 0:
                self._replay_container_cb.setCurrentIndex(idx)
        replay_codec = self._config.get_gsr_setting("replay_codec")
        if isinstance(replay_codec, str) and replay_codec:
            self._replay_codec_edit.setText(replay_codec)
        replay_duration = self._config.get_gsr_setting("replay_duration")
        if isinstance(replay_duration, int):
            self._replay_duration_sb.setValue(replay_duration)
        replay_audio = self._config.get_gsr_setting("replay_audio_device")
        if isinstance(replay_audio, str) and replay_audio:
            self._replay_audio_edit.setText(replay_audio)
        replay_area = self._config.get_gsr_setting("replay_record_area")
        if isinstance(replay_area, str):
            idx = self._replay_area_cb.findText(replay_area)
            if idx >= 0:
                self._replay_area_cb.setCurrentIndex(idx)
        self._replay_show_cursor_cb.setChecked(
            self._config.get_gsr_setting("replay_show_cursor") is not False
        )
        hotkey = self._config.get_hotkey()
        if hotkey and hotkey != "Alt+Z":
            self._hotkey_edit.setText(hotkey)
        overlay_auto_hide = self._config.get_gsr_setting("overlay_auto_hide")
        if isinstance(overlay_auto_hide, int):
            self._overlay_auto_hide_sb.setValue(overlay_auto_hide)

        # Storage path overrides
        for key in self._storage_fields:
            val = self._config.get(f"path_{key}", None)
            if val is not None and isinstance(val, str) and val.strip():
                self._storage_fields[key].setText(val)
        rclone_remote = self._config.get("path_rclone_remote", None)
        if rclone_remote:
            self._rclone_remote_edit.setText(str(rclone_remote))
        rclone_bucket = self._config.get("path_rclone_bucket", None)
        if rclone_bucket:
            self._rclone_bucket_edit.setText(str(rclone_bucket))
        base_url = self._config.get("path_base_url", None)
        if base_url:
            self._base_url_edit.setText(str(base_url))

    def _save_settings(self) -> None:
        """Persist all settings to config."""
        if self._config is None:
            return
        self._config.set("autostart", self._autostart_cb.isChecked())
        self._config.set("minimize_to_tray", self._minimize_tray_cb.isChecked())
        self._config.set("encode_timing", self._encode_timing_cb.currentText())
        # Video codec (GPU-agnostic encoder selection)
        encoder_label = self._video_encoder_cb.currentText()
        encoder_value = None
        for label, value in _VIDEO_ENCODER_OPTIONS:
            if label == encoder_label:
                encoder_value = value
                break
        if encoder_value is not None:
            self._config.set_preferred_codec(encoder_value)
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

        # Recording (GSR) settings
        self._config.set_gsr_setting(
            "replay_enabled", self._replay_enabled_cb.isChecked()
        )
        self._config.set_gsr_setting("replay_fps", self._replay_fps_sb.value())
        self._config.set_gsr_setting(
            "replay_quality", self._replay_quality_cb.currentText()
        )
        self._config.set_gsr_setting(
            "replay_container", self._replay_container_cb.currentText()
        )
        self._config.set_gsr_setting(
            "replay_codec", self._replay_codec_edit.text().strip()
        )
        self._config.set_gsr_setting(
            "replay_duration", self._replay_duration_sb.value()
        )
        self._config.set_gsr_setting(
            "replay_audio_device", self._replay_audio_edit.text().strip()
        )
        self._config.set_gsr_setting(
            "replay_record_area", self._replay_area_cb.currentText()
        )
        self._config.set_gsr_setting(
            "replay_show_cursor", self._replay_show_cursor_cb.isChecked()
        )
        self._config.set_gsr_setting(
            "hotkey_show_overlay", self._hotkey_edit.text().strip() or "Alt+Z"
        )
        self._config.set_gsr_setting(
            "overlay_auto_hide", self._overlay_auto_hide_sb.value()
        )

        # Storage path overrides
        for key, edit in self._storage_fields.items():
            val = edit.text().strip()
            if val:
                self._config.set_path(key, val)
            else:
                self._config.delete(f"path_{key}")

        for key, edit in (
            ("rclone_remote", self._rclone_remote_edit),
            ("rclone_bucket", self._rclone_bucket_edit),
            ("base_url", self._base_url_edit),
        ):
            val = edit.text().strip()
            if val:
                self._config.set_path(key, val)
            else:
                self._config.delete(f"path_{key}")

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
        self._video_encoder_cb.setCurrentIndex(0)  # Auto
        self._preset_cb.setCurrentIndex(5)
        self._cq_slider.setValue(23)
        self._bitrate_sb.setValue(12)
        self._audio_codec_cb.setCurrentIndex(0)
        self._process_list_edit.clear()
        self._scan_interval_sb.setValue(3)
        self._game_exit_cb.setCurrentIndex(0)

        # Reset recording settings
        self._replay_enabled_cb.setChecked(False)
        self._replay_fps_sb.setValue(60)
        self._replay_quality_cb.setCurrentText("very_high")
        self._replay_container_cb.setCurrentIndex(0)
        self._replay_codec_edit.clear()
        self._replay_duration_sb.setValue(120)
        self._replay_audio_edit.clear()
        self._replay_area_cb.setCurrentIndex(0)
        self._replay_show_cursor_cb.setChecked(True)
        self._hotkey_edit.clear()
        self._overlay_auto_hide_sb.setValue(8)

        # Reset storage paths
        for edit in self._storage_fields.values():
            edit.clear()
        self._rclone_remote_edit.clear()
        self._rclone_bucket_edit.clear()
        self._base_url_edit.clear()
        if self._config is not None:
            self._config.reset_paths()

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
        db_path = os.path.expanduser("~/.config/moment/clips.db")
        if self._config is not None:
            db_path = os.path.join(self._config.get_path("db_dir"), "clips.db")
        try:
            os.unlink(db_path)
            QMessageBox.information(
                self, "Database Reset",
                "Database deleted. Restart Moment to recreate it."
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
