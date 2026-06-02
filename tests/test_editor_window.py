"""Tests for moment.ui.editor.editor_window — EditorWindow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QMessageBox

from moment.core.models import EditProfile
from moment.ui.editor.editor_window import EditorWindow

pytestmark = [pytest.mark.gui]


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get_edit_profile.return_value = None  # No existing profile
    return store


@pytest.fixture
def window(qapp, mock_store):
    """Create an EditorWindow, properly cleaned up after each test."""

    w = EditorWindow(clip_id="test", store=mock_store)
    yield w
    w.close()
    w.deleteLater()


class TestEditorWindowInit:
    def test_create_without_existing_profile(self, window):
        assert window._clip_id == "test"
        assert window._profile is not None
        assert window._profile.clip_id == "test"

    def test_create_with_existing_profile(self, qapp, mock_store):
        existing = EditProfile(clip_id="existing-id")
        mock_store.get_edit_profile.return_value = existing
        w = EditorWindow(clip_id="existing-id", store=mock_store)
        assert w._profile is existing
        w.close()
        w.deleteLater()

    def test_window_title(self, window):
        assert "Editor" in window.windowTitle()

    def test_minimum_size_set(self, window):
        assert window.minimumWidth() > 0
        assert window.minimumHeight() > 0

    def test_signals_exist(self, window):
        assert hasattr(window, "profile_saved")
        assert hasattr(window, "close_requested")


class TestEditorWindowTabs:
    def test_four_tabs_exist(self, window):
        assert window._tabs.count() == 4

    def test_tab_labels(self, window):
        labels = [window._tabs.tabText(i) for i in range(window._tabs.count())]
        assert "Timeline" in labels
        assert "Filters" in labels
        assert "Merge" in labels
        assert "Music" in labels


class TestEditorWindowAutoSave:
    def test_schedule_save_starts_timer(self, window):
        window._save_timer.stop()
        window._schedule_save()
        assert window._save_timer.isActive()

    def test_do_save_persists_profile(self, window):
        window._do_save()
        # mock_store is shared; check that save_edit_profile was called
        window._store.save_edit_profile.assert_called_once()

    def test_do_save_increments_version(self, window):
        original_version = window._profile.edit_version
        window._do_save()
        assert window._profile.edit_version == original_version + 1

    def test_do_save_emits_saved_signal(self, window):
        fired = []
        window.profile_saved.connect(lambda cid: fired.append(cid))
        window._do_save()
        assert fired == ["test"]


class TestEditorWindowClose:
    def test_close_event_saves_and_emits(self, window):
        # Make window dirty first so closeEvent triggers save
        window._dirty = True
        fired = []
        window.close_requested.connect(lambda: fired.append(True))
        with patch(
            "moment.ui.editor.editor_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Save,
        ):
            window.closeEvent(QCloseEvent())
        window._store.save_edit_profile.assert_called_once()
        assert len(fired) == 1


class TestEditorWindowPanels:
    def test_panel_instances_exist(self, window):
        assert window._timeline is not None
        assert window._filters is not None
        assert window._merge is not None
        assert window._music is not None

    def test_panel_signals_connected(self, window):
        # Emit profile_changed from a panel and verify save is triggered
        window._save_timer.stop()
        window._timeline.profile_changed.emit()
        assert window._save_timer.isActive()
