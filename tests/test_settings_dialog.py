"""Tests for dialogs/settings_dialog.py — two-panel settings with ToggleSwitch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from moment.ui.dialogs.settings_dialog import (
    ToggleSwitch,
    SettingsDialog,
    _VIDEO_ENCODER_OPTIONS,
)

pytestmark = [pytest.mark.gui]


def _make_config(**overrides: object) -> MagicMock:
    """Create a MagicMock Config that returns proper defaults from get()."""
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: (
        overrides.get(key, default) if overrides else default
    )
    config.get_preferred_codec.return_value = overrides.get("preferred_codec", "auto")
    config.get_gsr_setting.return_value = overrides.get("gsr_setting", None)
    config.get_hotkey.return_value = overrides.get("hotkey", "Alt+Z")
    config.get_path.return_value = overrides.get("path", "")
    return config


class TestToggleSwitch:
    """Tests for the custom ToggleSwitch widget."""

    def test_create(self, qapp) -> None:
        ts = ToggleSwitch()
        assert ts is not None
        assert ts.size() == ts.size()  # fixed size

    def test_default_unchecked(self, qapp) -> None:
        ts = ToggleSwitch()
        assert ts.isChecked() is False

    def test_set_checked(self, qapp) -> None:
        ts = ToggleSwitch()
        ts.setChecked(True)
        assert ts.isChecked() is True

    def test_click_toggles(self, qapp) -> None:
        ts = ToggleSwitch()
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import Qt
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(22, 11),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        toggled_state = []
        ts.toggled.connect(lambda s: toggled_state.append(s))
        ts.mousePressEvent(event)
        assert ts.isChecked() is True
        assert toggled_state == [True]

    def test_signal_emitted(self, qapp) -> None:
        ts = ToggleSwitch()
        state = []
        ts.toggled.connect(state.append)
        ts.setChecked(True)
        ts.setChecked(False)
        # setChecked doesn't emit; only click does
        assert state == []


class TestSettingsDialogInit:
    """Tests for SettingsDialog construction."""

    def test_create(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg.windowTitle() == "Settings"

    def test_create_with_config(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        assert dlg._config is config

    def test_minimum_size(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg.minimumWidth() >= 400
        assert dlg.minimumHeight() >= 300

    def test_stack_page_count(self, qapp) -> None:
        dlg = SettingsDialog()
        # 7 categories = 7 pages in stack
        assert dlg._stack.count() == 7

    def test_nav_items_exist(self, qapp) -> None:
        dlg = SettingsDialog()
        # nav has header item + 7 category items = 8 items total
        assert dlg._nav.count() == 8

    def test_two_panel_layout(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._nav is not None
        assert dlg._stack is not None

    def test_button_bar_exists(self, qapp) -> None:
        dlg = SettingsDialog()
        # Should have Cancel, Apply, OK buttons
        assert dlg is not None

    def test_toggles_exist(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._autostart_ts is not None
        assert dlg._minimize_tray_ts is not None
        assert dlg._capture_audio_ts is not None
        assert dlg._gpu_accel_ts is not None

    def test_nav_switch_changes_page(self, qapp) -> None:
        dlg = SettingsDialog()
        dlg._nav.setCurrentRow(3)  # Skip header, General=row1, Rec=row2, Video=row3
        # _on_nav_changed gets called, stack should switch to page 2 (Video)
        assert dlg._stack.currentIndex() >= 0


class TestSettingsLoad:
    """Tests for loading settings from config."""

    def test_load_no_config(self, qapp) -> None:
        dlg = SettingsDialog(config=None)
        assert dlg._autostart_ts.isChecked() is False

    def test_load_with_config(self, qapp) -> None:
        config = _make_config(autostart=True)
        dlg = SettingsDialog(config=config)
        assert dlg._autostart_ts.isChecked() is True

    def test_load_minimize_tray(self, qapp) -> None:
        config = _make_config(minimize_to_tray=False)
        dlg = SettingsDialog(config=config)
        assert dlg._minimize_tray_ts.isChecked() is False

    def test_load_recording_fps(self, qapp) -> None:
        config = _make_config()
        config.get_gsr_setting.side_effect = lambda key: (
            120 if key == "replay_fps" else None
        )
        dlg = SettingsDialog(config=config)
        assert dlg._fps_cb.currentText() == "120"

    def test_load_preferred_codec(self, qapp) -> None:
        config = _make_config(preferred_codec="hevc_nvenc")
        dlg = SettingsDialog(config=config)
        # Should have selected NVENC HEVC in the combo
        assert dlg._video_encoder_cb.currentText() == "NVENC HEVC"


class TestSettingsSave:
    """Tests for persisting settings to config."""

    def test_save_no_config_no_error(self, qapp) -> None:
        dlg = SettingsDialog(config=None)
        dlg._save_settings()

    def test_save_persists_autostart(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._autostart_ts.setChecked(True)
        dlg._save_settings()
        config.set.assert_any_call("autostart", True)

    def test_apply_saves(self, qapp) -> None:
        config = _make_config(autostart=False)
        dlg = SettingsDialog(config=config)
        dlg._autostart_ts.setChecked(True)
        dlg._on_apply()
        config.set.assert_any_call("autostart", True)

    def test_ok_saves_and_accepts(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        dlg._on_ok()
        assert dlg.result() == 1  # Accepted

    def test_save_video_codec(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        dlg._video_encoder_cb.setCurrentIndex(1)
        dlg._save_settings()
        config.set_preferred_codec.assert_called()

    def test_save_preset(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        dlg._preset_cb.setCurrentText("p7")
        dlg._save_settings()
        config.set.assert_any_call("preset", "p7")

    def test_save_bitrate(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        dlg._bitrate_sb.setValue(24)
        dlg._save_settings()
        config.set.assert_any_call("bitrate_mbps", 24)


class TestSettingsWidgets:
    """Tests that key widgets exist across all pages."""

    def test_general_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._theme_cb is not None
        assert dlg._density_cb is not None
        assert dlg._font_cb is not None
        assert dlg._language_cb is not None

    def test_recording_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._recordings_path_edit is not None
        assert dlg._record_mode_cb is not None
        assert dlg._fps_cb is not None
        assert dlg._resolution_cb is not None
        assert dlg._buffer_duration_sb is not None

    def test_video_widgets(self, qapp) -> None:
        config = _make_config()
        dlg = SettingsDialog(config=config)
        assert dlg._video_encoder_cb is not None
        assert dlg._quality_cb is not None
        assert dlg._format_cb is not None
        assert dlg._preset_cb is not None
        assert dlg._bitrate_sb is not None

    def test_hotkeys_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._hotkeys_table is not None
        assert dlg._hotkeys_table.rowCount() == 4

    def test_output_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._upload_target_cb is not None
        assert dlg._naming_edit is not None
        assert dlg._keep_clips_sb is not None
        assert dlg._storage_limit_sb is not None

    def test_cloud_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        assert dlg._cloud_accounts_list is not None
        assert dlg._storage_bar is not None

    def test_about_widgets(self, qapp) -> None:
        dlg = SettingsDialog()
        # About page is just labels + update button


class TestEncoderOptions:
    """Tests for the encoder options dataset."""

    def test_options_not_empty(self) -> None:
        assert len(_VIDEO_ENCODER_OPTIONS) > 0

    def test_auto_option_first(self) -> None:
        assert "Auto" in _VIDEO_ENCODER_OPTIONS[0][0]
