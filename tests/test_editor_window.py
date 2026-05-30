"""Tests for moment.ui.editor.editor_window — EditorWindow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QMessageBox

from moment.core.models import EditProfile
from moment.ui.editor.editor_window import EditorWindow


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get_edit_profile.return_value = None  # No existing profile
    return store


class TestEditorWindowInit:
    def test_create_without_existing_profile(self, qapp, mock_store):
        window = EditorWindow(clip_id="test-id", store=mock_store)
        assert window._clip_id == "test-id"
        assert window._profile is not None
        assert window._profile.clip_id == "test-id"

    def test_create_with_existing_profile(self, qapp, mock_store):
        existing = EditProfile(clip_id="existing-id")
        mock_store.get_edit_profile.return_value = existing
        window = EditorWindow(clip_id="existing-id", store=mock_store)
        assert window._profile is existing

    def test_window_title(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        assert "Editor" in window.windowTitle()

    def test_minimum_size_set(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        assert window.minimumWidth() > 0
        assert window.minimumHeight() > 0

    def test_signals_exist(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        assert hasattr(window, "profile_saved")
        assert hasattr(window, "close_requested")


class TestEditorWindowTabs:
    def test_four_tabs_exist(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        assert window._tabs.count() == 4

    def test_tab_labels(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        labels = [window._tabs.tabText(i) for i in range(window._tabs.count())]
        assert "Timeline" in labels
        assert "Filters" in labels
        assert "Merge" in labels
        assert "Music" in labels


class TestEditorWindowAutoSave:
    def test_schedule_save_starts_timer(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        window._save_timer.stop()
        window._schedule_save()
        assert window._save_timer.isActive()

    def test_do_save_persists_profile(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        window._do_save()
        mock_store.save_edit_profile.assert_called_once()

    def test_do_save_increments_version(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        original_version = window._profile.edit_version
        window._do_save()
        assert window._profile.edit_version == original_version + 1

    def test_do_save_emits_saved_signal(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        fired = []
        window.profile_saved.connect(lambda cid: fired.append(cid))
        window._do_save()
        assert fired == ["test"]


class TestEditorWindowClose:
    def test_close_event_saves_and_emits(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        # Make window dirty first so closeEvent triggers save
        window._dirty = True
        fired = []
        window.close_requested.connect(lambda: fired.append(True))
        with patch(
            "moment.ui.editor.editor_window.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Save,
        ):
            window.closeEvent(QCloseEvent())
        mock_store.save_edit_profile.assert_called_once()
        assert len(fired) == 1


class TestEditorWindowPanels:
    def test_panel_instances_exist(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        assert window._timeline is not None
        assert window._filters is not None
        assert window._merge is not None
        assert window._music is not None

    def test_panel_signals_connected(self, qapp, mock_store):
        window = EditorWindow(clip_id="test", store=mock_store)
        # Emit profile_changed from a panel and verify save is triggered
        window._save_timer.stop()
        window._timeline.profile_changed.emit()
        assert window._save_timer.isActive()
