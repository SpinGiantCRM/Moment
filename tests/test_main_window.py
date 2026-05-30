"""Tests for moment.ui.main_window — MainWindow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from moment.ui.main_window import MainWindow


class TestMainWindowInit:
    def test_create_default(self, qapp):
        window = MainWindow()
        assert window.windowTitle() == "moment"
        assert window.width() > 0
        assert window.height() > 0

    def test_create_with_store(self, qapp):
        store = MagicMock()
        window = MainWindow(store=store)
        assert window._store is store

    def test_signals_exist(self, qapp):
        window = MainWindow()
        assert hasattr(window, "close_to_tray")

    def test_status_bar_initial(self, qapp):
        window = MainWindow()
        assert window._status_label.text() == "Ready"

    def test_default_minimize_to_tray(self, qapp):
        window = MainWindow()
        assert window._minimize_to_tray is True


class TestMainWindowPages:
    def test_pages_created(self, qapp):
        window = MainWindow()
        assert window._stack.count() == 6
        assert window._recording_page is not None
        assert window._grid_page is not None
        assert window._player_page is not None
        assert window._stats_page is not None
        assert window._trash_page is not None
        assert window._webhook_page is not None

    def test_page_properties(self, qapp):
        window = MainWindow()
        assert window.recording_page is window._recording_page
        assert window.grid_page is window._grid_page
        assert window.player_page is window._player_page
        assert window.stats_page is window._stats_page
        assert window.trash_page is window._trash_page
        assert window.webhook_page is window._webhook_page

    def test_nav_buttons_exist(self, qapp):
        window = MainWindow()
        assert len(window._nav_buttons) == 6


class TestMainWindowNavigation:
    def test_switch_page_updates_buttons(self, qapp):
        window = MainWindow()
        window._switch_page(1)  # Grid
        assert window._nav_buttons[1].isChecked()

    def test_switch_page_updates_stack(self, qapp):
        window = MainWindow()
        window._switch_page(0)  # Recording
        assert window._stack.currentIndex() == 0

    def test_show_player(self, qapp):
        window = MainWindow()
        window.show_player("test-clip-id")
        assert window._stack.currentIndex() == 2  # _PAGE_PLAYER


class TestMainWindowStatus:
    def test_update_status(self, qapp):
        window = MainWindow()
        window._update_status("Processing...")
        assert window._status_label.text() == "Processing..."

    def test_set_pipeline_status(self, qapp):
        window = MainWindow()
        window.set_pipeline_status("Encoding clip-1")
        assert window._status_label.text() == "Encoding clip-1"

    def test_grid_selection_updates_status(self, qapp):
        window = MainWindow()
        window._on_grid_selection_changed(3)
        assert "3" in window._status_label.text()
        assert "selected" in window._status_label.text()

    def test_grid_selection_zero_resets_status(self, qapp):
        window = MainWindow()
        window._on_grid_selection_changed(0)
        assert window._status_label.text() == "Ready"


class TestMainWindowCloseEvent:
    def test_hide_to_tray(self, qapp):
        window = MainWindow()
        window._minimize_to_tray = True
        from PyQt6.QtGui import QCloseEvent
        event = QCloseEvent()
        toggled = []
        window.close_to_tray.connect(lambda: toggled.append(True))
        window.closeEvent(event)
        assert len(toggled) == 1

    def test_quit_directly(self, qapp):
        window = MainWindow()
        window._minimize_to_tray = False
        from PyQt6.QtGui import QCloseEvent
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()


class TestMainWindowMinimize:
    def test_set_minimize_to_tray(self, qapp):
        window = MainWindow()
        window.set_minimize_to_tray(False)
        assert window._minimize_to_tray is False
        window.set_minimize_to_tray(True)
        assert window._minimize_to_tray is True


class TestMainWindowRefresh:
    def test_refresh_calls_grid_refresh(self, qapp):
        window = MainWindow()
        window._grid_page.refresh = MagicMock()
        window.refresh()
        window._grid_page.refresh.assert_called_once()


class TestMainWindowBatchAction:
    def test_batch_delete_calls_store(self, qapp):
        store = MagicMock()
        window = MainWindow(store=store)
        window._grid_page.refresh = MagicMock()
        # Mock QMessageBox.question to return Yes so delete proceeds
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window._on_batch_action("Delete", ["clip-1", "clip-2"])
        assert store.delete_clip.call_count == 2
        window._grid_page.refresh.assert_called_once()

    def test_batch_delete_no_store(self, qapp):
        window = MainWindow()
        window._on_batch_action("Delete", ["clip-1"])

    def test_batch_other_action_noop(self, qapp):
        store = MagicMock()
        window = MainWindow(store=store)
        window._on_batch_action("Export", ["clip-1"])
        store.delete_clip.assert_not_called()


class TestMainWindowRecordingHandlers:
    def test_start_recording(self, qapp):
        window = MainWindow()
        window._on_start_recording()
        # After start_recording, recording page should be in recording state
        assert window._recording_page.is_recording()

    def test_stop_recording(self, qapp):
        window = MainWindow()
        # Start first, then stop
        window._on_start_recording()
        window._on_stop_recording()
        # After stop_recording, recording page should be in ready state
        assert not window._recording_page.is_recording()

    def test_save_clip(self, qapp):
        window = MainWindow()
        window._on_recording_save_clip(30)
        # No crash is the main assertion

    def test_clip_restored(self, qapp):
        window = MainWindow()
        window._grid_page.refresh = MagicMock()
        window._on_clip_restored("clip-1")
        window._grid_page.refresh.assert_called_once()

    def test_trash_changed(self, qapp):
        window = MainWindow()
        window._grid_page.refresh = MagicMock()
        window._on_trash_changed()
        window._grid_page.refresh.assert_called_once()
