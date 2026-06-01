"""Tests for dialogs/settings_dialog.py — tabbed settings with persistence."""

from __future__ import annotations
import pytest

from unittest.mock import MagicMock, patch

from moment.ui.dialogs.settings_dialog import _VIDEO_ENCODER_OPTIONS, SettingsDialog
pytestmark = [pytest.mark.gui]


class TestVideoEncoderOptions:
    """Tests for the encoder options dataset."""

    def test_options_not_empty(self) -> None:

        assert len(_VIDEO_ENCODER_OPTIONS) > 0

    def test_auto_option_first(self) -> None:
        assert "Auto" in _VIDEO_ENCODER_OPTIONS[0][0]

def _make_config(**overrides: object) -> MagicMock:
    """Create a MagicMock Config that returns proper defaults from get()."""
    config = MagicMock()
    # Default: get() returns the supplied default value
    config.get.side_effect = lambda key, default=None: (
        overrides.get(key, default) if overrides else default
    )
    config.get_preferred_codec.return_value = overrides.get("preferred_codec", "auto")
    config.get_gsr_setting.return_value = overrides.get("gsr_setting", None)
    config.get_hotkey.return_value = overrides.get("hotkey", "Alt+Z")
    return config

class TestSettingsDialogInit:
    """Tests for SettingsDialog construction."""

    def test_create(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg.windowTitle() == "Settings"

    def test_create_with_config(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        assert dlg._config is config

    def test_tab_count(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._tabs.count() == 7

    def test_tab_labels(self, qapp) -> None:
        dlg = SettingsDialog()
        labels = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
        assert "General" in labels
        assert "Encoding" in labels
        assert "Notifications" in labels
        assert "Game" in labels[3] or "Detection" in labels[3]
        assert "Recording" in labels
        assert "Appearance" in labels
        assert "Storage" in labels[6]

    def test_minimum_size(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg.minimumWidth() >= 400
        assert dlg.minimumHeight() >= 400

class TestSettingsLoad:
    """Tests for loading settings from config."""

    def test_load_no_config(self, qapp) -> None:
        dlg = SettingsDialog(config=None)
        # Should not raise — default state
        assert dlg._autostart_cb.isChecked() is False

    def test_load_with_config(self, qapp) -> None:
        config = _make_config(autostart=True)
        dlg = SettingsDialog(config=config)
        assert dlg._autostart_cb.isChecked() is True

    def test_load_encoding_settings(self, qapp) -> None:
        config = _make_config(
            autostart=False, minimize_to_tray=True,
            encode_timing="after_game", preset="p6",
            cq=23, bitrate_mbps=12, audio_codec="aac",
            noise_suppression=False, toast_success=True,
            toast_info=True, toast_warning=True,
            toast_error=True, review_cards=True,
            sounds=False, auto_detect_games=True,
            game_processes="", game_scan_interval=3,
            pause_encode_during_game=True,
            pause_thumbnail_during_game=True,
            minimize_during_game=True,
            game_exit_behavior="open_editor",
        )
        dlg = SettingsDialog(config=config)
        assert dlg._preset_cb.currentText() == "p6"
        assert dlg._cq_slider.value() == 23

class TestSettingsSave:
    """Tests for persisting settings to config."""

    def test_save_no_config_no_error(self, qapp) -> None:
        dlg = SettingsDialog(config=None)
        dlg._save_settings()  # Should not raise

    def test_save_persists_to_config(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._autostart_cb.setChecked(True)
        dlg._save_settings()
        config.set.assert_any_call("autostart", True)

    def test_tab_change_saves(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._autostart_cb.setChecked(True)
        dlg._on_tab_changed(1)  # Switch to Encoding tab — triggers save
        config.set.assert_any_call("autostart", True)

    def test_close_saves(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._on_close()
        assert dlg.result() == 1

class TestSettingsDefaultPaths:
    """Tests for _get_path_default helper."""

    def test_db_dir_default(self) -> None:
        val = SettingsDialog._get_path_default("db_dir")
        assert "moment" in val.lower()

    def test_unknown_key_returns_empty(self) -> None:
        val = SettingsDialog._get_path_default("nonexistent")
        assert val == ""

class TestResetDefaults:
    """Tests for resetting settings to defaults."""

    @patch("moment.ui.dialogs.settings_dialog.QMessageBox.question",
           return_value=16384)  # QMessageBox.Yes = 16384
    def test_reset_defaults(self, mock_box, qapp) -> None:
        dlg = SettingsDialog()
        dlg._autostart_cb.setChecked(True)
        dlg._on_reset_defaults()
        assert dlg._autostart_cb.isChecked() is False

    @patch("moment.ui.dialogs.settings_dialog.QMessageBox.question",
           return_value=65536)  # QMessageBox.No = 65536
    def test_reset_defaults_cancelled(self, mock_box, qapp) -> None:
        dlg = SettingsDialog()
        dlg._autostart_cb.setChecked(True)
        dlg._on_reset_defaults()
        assert dlg._autostart_cb.isChecked() is True  # unchanged

class TestSettingsWidgets:
    """Tests that key widgets exist across all tabs."""

    def test_general_tab_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._autostart_cb is not None
        assert dlg._minimize_tray_cb is not None
        assert dlg._encode_timing_cb is not None

    def test_encoding_tab_widgets(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        assert dlg._video_encoder_cb is not None
        assert dlg._preset_cb is not None
        assert dlg._cq_slider is not None
        assert dlg._bitrate_sb is not None
        assert dlg._audio_codec_cb is not None

    def test_notifications_tab_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._toast_success_cb is not None
        assert dlg._toast_info_cb is not None
        assert dlg._toast_warning_cb is not None
        assert dlg._toast_error_cb is not None

    def test_game_tab_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._auto_detect_cb is not None
        assert dlg._process_list_edit is not None
        assert dlg._scan_interval_sb is not None

    def test_recording_tab_widgets(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        assert dlg._replay_enabled_cb is not None
        assert dlg._replay_fps_sb is not None
        assert dlg._replay_quality_cb is not None
        assert dlg._replay_container_cb is not None
        assert dlg._replay_duration_sb is not None

    def test_storage_tab_widgets(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        assert dlg._rclone_remote_edit is not None
        assert dlg._rclone_bucket_edit is not None
        assert dlg._base_url_edit is not None
        assert len(dlg._storage_fields) > 0

class TestVideoCodecSettings:
    """Tests for video encoder selection and persistence."""

    def test_save_video_codec(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._video_encoder_cb.setCurrentIndex(1)  # NVENC H.264
        dlg._save_settings()
        config.set_preferred_codec.assert_called()


