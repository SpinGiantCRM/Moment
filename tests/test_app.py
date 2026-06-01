"""Tests for moment.ui.app — AppManager and CLI entry point."""

from __future__ import annotations
import pytest

from unittest.mock import MagicMock, patch
pytestmark = [pytest.mark.gui]


class TestParseArgs:
    def test_defaults(self):
        from moment.ui.app import _parse_args
        args = _parse_args([])
        assert args.minimized is False
        assert args.settings is False
        assert args.open_encoded is False
        assert args.verbose is False
        assert args.version is False

    def test_minimized(self):
        from moment.ui.app import _parse_args
        args = _parse_args(["--minimized"])
        assert args.minimized is True

    def test_settings(self):
        from moment.ui.app import _parse_args
        args = _parse_args(["--settings"])
        assert args.settings is True

    def test_open_encoded(self):
        from moment.ui.app import _parse_args
        args = _parse_args(["--open-encoded"])
        assert args.open_encoded is True

    def test_verbose(self):
        from moment.ui.app import _parse_args
        args = _parse_args(["--verbose"])
        assert args.verbose is True

    def test_version(self):
        from moment.ui.app import _parse_args
        args = _parse_args(["--version"])
        assert args.version is True

class TestAppManagerInit:
    def test_init_defaults(self):
        from moment.ui.app import AppManager, _parse_args
        args = _parse_args([])
        mgr = AppManager(args)
        assert mgr.app is None
        assert mgr.tray is None
        assert mgr._window is None
        assert mgr._store is None

    def test_init_parses_args_if_none(self):
        from moment.ui.app import AppManager
        with patch("sys.argv", ["moment"]):
            mgr = AppManager()
            assert mgr._args is not None

@patch("sys.exit")
@patch("builtins.print")
class TestPrintVersion:
    def test_version_flag_prints_and_exits(self, mock_print, mock_exit):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args(["--version"]))
        mgr.init()
        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(0)

@patch("sys.exit")
class TestOpenEncoded:
    @patch("moment.utils.subprocess.Popen_sandboxed")
    def test_open_encoded_opens_dir(self, mock_popen, mock_exit):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args(["--open-encoded"]))
        mgr.init()
        mock_popen.assert_called_once()
        # _open_encoded_dir calls sys.exit(0), then init() also calls
        # sys.exit(0) — both are recorded since sys.exit is mocked
        mock_exit.assert_called_with(0)

    @patch("moment.utils.subprocess.Popen_sandboxed", side_effect=FileNotFoundError)
    def test_open_encoded_failure(self, mock_popen, mock_exit):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args(["--open-encoded"]))
        mgr.init()
        # _open_encoded_dir calls sys.exit(1), then init() calls sys.exit(0)
        mock_exit.assert_any_call(1)

class TestPrintVersionStatic:
    def test_print_version(self):
        from moment.ui.app import AppManager
        AppManager._print_version()

class TestAppManagerQuit:
    @patch("moment.ui.app.QApplication.quit")
    def test_on_quit_shuts_down_cleanly(self, mock_quit):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._store = MagicMock()
        mgr._pipeline = None
        mgr._gsr_controller = None
        mgr._gsr_watcher = None
        mgr._hotkey_manager = None
        mgr._overlay = None
        mgr._on_quit()
        mgr._store.close.assert_called_once()
        mock_quit.assert_called_once()

    @patch("moment.ui.app.QApplication.quit")
    def test_on_quit_with_gsr(self, mock_quit):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._store = MagicMock()
        mgr._gsr_controller = MagicMock()
        mgr._gsr_watcher = MagicMock()
        mgr._hotkey_manager = MagicMock()
        mgr._overlay = MagicMock()
        mgr._pipeline = MagicMock()
        mgr._on_quit()
        mgr._gsr_controller.stop.assert_called_once()
        mgr._gsr_watcher.stop.assert_called_once()
        mgr._hotkey_manager.unregister.assert_called_once()
        mgr._overlay.hide.assert_called_once()
        mgr._pipeline.shutdown.assert_called_once()
        mgr._store.close.assert_called_once()

class TestAppManagerProperties:
    def test_app_property(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        assert mgr.app is None

    def test_tray_property(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        assert mgr.tray is None

@patch("sys.exit")
@patch("moment.ui.app.AppManager._init_services")
@patch("moment.ui.app.AppManager._create_window")
@patch("moment.ui.app.TrayIcon")
class TestAppManagerInitMocks:
    def test_init_creates_qapp(
        self, mock_tray, mock_create, mock_svc, mock_exit,
    ):
        from moment.ui.app import AppManager, _parse_args
        args = _parse_args([])
        mgr = AppManager(args)
        mgr._args.version = False
        mgr._args.open_encoded = False

        # Configure mocks
        mock_tray_inst = MagicMock()
        mock_tray.return_value = mock_tray_inst

        mgr.init()
        assert mgr._qapp is not None

    def test_init_creates_tray(
        self, mock_tray, mock_create, mock_svc, mock_exit,
    ):
        from moment.ui.app import AppManager, _parse_args
        args = _parse_args([])
        mgr = AppManager(args)
        mgr._args.version = False
        mgr._args.open_encoded = False

        mock_tray_inst = MagicMock()
        mock_tray.return_value = mock_tray_inst

        mgr.init()
        mock_tray.assert_called_once()
        mock_tray_inst.show.assert_called_once()

    def test_settings_flag_opens_dialog(
        self, mock_tray, mock_create, mock_svc, mock_exit,
    ):
        from moment.ui.app import AppManager, _parse_args
        args = _parse_args(["--settings"])
        mgr = AppManager(args)
        mgr._args.version = False
        mgr._args.open_encoded = False

        mock_tray_inst = MagicMock()
        mock_tray.return_value = mock_tray_inst

        from PyQt6.QtGui import QFont, QIcon

        # Mock _detect_high_contrast to avoid MagicMock vs int comparison;
        # provide real QFont/QIcon since QApplication is real.
        # Mock _on_settings because it opens a modal dialog (blocking).
        with patch("moment.ui.app.stylesheet", return_value=""), \
             patch("moment.ui.app.app_font", return_value=QFont()), \
             patch("moment.ui.app.load_icon", return_value=QIcon()), \
             patch("moment.ui.app.sys.excepthook"), \
             patch.object(AppManager, "_detect_high_contrast", return_value=False), \
             patch.object(AppManager, "_on_settings"):
            mgr.init()
            # settings_requested should be connected
            # We verify tray was created
            assert mock_tray.called

class TestAppManagerToggleWindow:
    @patch("moment.ui.app.AppManager._create_window")
    def test_toggle_shows_hidden_window(self, mock_create):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._window = MagicMock()
        mgr._window.isVisible.return_value = False
        mgr._toggle_window()
        mgr._window.show.assert_called_once()
        mgr._window.raise_.assert_called_once()

    @patch("moment.ui.app.AppManager._create_window")
    def test_toggle_hides_visible_window(self, mock_create):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._window = MagicMock()
        mgr._window.isVisible.return_value = True
        mgr._toggle_window()
        mgr._window.hide.assert_called_once()

    @patch("moment.ui.app.AppManager._create_window")
    def test_toggle_creates_window_if_none(self, mock_create):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._window = None
        mgr._toggle_window()
        mock_create.assert_called_once()

class TestAppManagerWindowHidden:
    def test_window_hidden_updates_tray(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._tray = MagicMock()
        mgr._on_window_hidden()
        mgr._tray.update_status.assert_called_once()

class TestAppManagerActionHandlers:
    def test_save_replay_action(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._gsr_controller = MagicMock()
        mgr._on_action("save_replay:30")
        mgr._gsr_controller.save_replay.assert_called_once()

    def test_unknown_action(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._on_action("unknown_action")

class TestAppManagerExec:
    def test_exec_returns_1_if_no_qapp(self):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        result = mgr.exec()
        assert result == 1

class TestAppManagerInitServices:
    @patch("moment.core.config.Config")
    @patch("moment.core.store.Store")
    @patch("moment.utils.logging.setup_logging")
    @patch("moment.ui.app.AppManager._init_gsr")
    @patch("moment.ui.app.AppManager._init_pipeline")
    def test_init_services_success(
        self, mock_pipeline, mock_gsr, mock_log, mock_store_cls, mock_config_cls,
    ):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._config = None
        mgr._store = None
        mgr._init_services()
        assert mgr._config is not None
        assert mgr._store is not None

    @patch("moment.core.config.Config", side_effect=Exception("no db"))
    def test_init_services_failure_handled(self, mock_config):
        from moment.ui.app import AppManager, _parse_args
        mgr = AppManager(_parse_args([]))
        mgr._init_services()
        # Should not raise, just logs warning

class TestGlobalExcepthook:
    def test_global_excepthook(self):
        from moment.ui.app import _global_excepthook
        # Should not raise
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_type, exc_value, exc_tb = sys.exc_info()
            with patch("PyQt6.QtWidgets.QMessageBox"):
                _global_excepthook(exc_type, exc_value, exc_tb)


