"""Tests for moment.ui.editor.merge_panel — MergePanel."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt

from moment.core.models import Clip, ClipStatus, ClipType
from moment.ui.editor.merge_panel import MergePanel
pytestmark = [pytest.mark.gui]


@pytest.fixture

def mock_store():
    store = MagicMock()
    store.get_clip.return_value = Clip(
        id="test-id",
        stem="test_clip",
        source_path="/tmp/test.mp4",
        duration=10.0,
        file_size=1024000,
        title="Test Clip",
        game="Test Game",
        status=ClipStatus.DONE,
        clip_type=ClipType.VIDEO,
    )
    return store

class TestMergePanelInit:
    def test_creates_with_store(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        assert panel.clip_ids == []
        assert panel.transitions == []

    def test_properties_return_copies(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        ids = panel.clip_ids
        assert ids == []
        ids.append("x")
        assert panel.clip_ids == []  # unaffected

    def test_signals_exist(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        assert hasattr(panel, "profile_changed")
        assert hasattr(panel, "preview_requested")

class TestMergePanelClipOps:
    def test_add_clip(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("abc-123")
        assert "abc-123" in panel.clip_ids

    def test_add_clip_no_duplicate(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("abc-123")
        panel.add_clip("abc-123")
        assert panel.clip_ids == ["abc-123"]

    def test_add_clip_emits_signal(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        fired = []
        panel.profile_changed.connect(lambda: fired.append(True))
        panel.add_clip("clip-1")
        assert len(fired) == 1

    def test_remove_clip_no_selection(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("abc")
        panel._on_remove_clip()  # no selection
        assert panel.clip_ids == ["abc"]

    def test_remove_clip_with_selection(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        panel.add_clip("c")
        # Select row 1 ("b")
        panel._list.setCurrentRow(1)
        panel._on_remove_clip()
        assert panel.clip_ids == ["a", "c"]

    def test_remove_clip_last_item(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("only")
        panel._list.setCurrentRow(0)
        panel._on_remove_clip()
        assert panel.clip_ids == []

class TestMergePanelReorder:
    def test_move_up(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        panel.add_clip("c")
        panel._list.setCurrentRow(1)  # "b"
        panel._on_move_up()
        assert panel.clip_ids == ["b", "a", "c"]

    def test_move_up_first_item_noop(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        panel._list.setCurrentRow(0)
        panel._on_move_up()
        assert panel.clip_ids == ["a", "b"]

    def test_move_down(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        panel.add_clip("c")
        panel._list.setCurrentRow(1)
        panel._on_move_down()
        assert panel.clip_ids == ["a", "c", "b"]

    def test_move_down_last_item_noop(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        panel._list.setCurrentRow(1)
        panel._on_move_down()
        assert panel.clip_ids == ["a", "b"]

class TestMergePanelPreview:
    def test_preview_no_clips(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        fired = []
        panel.preview_requested.connect(lambda ids: fired.append(ids))
        panel._on_preview()
        assert fired == []

    def test_preview_with_clips(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("a")
        panel.add_clip("b")
        fired = []
        panel.preview_requested.connect(lambda ids: fired.append(ids))
        panel._on_preview()
        assert fired == [["a", "b"]]

class TestMergePanelRefreshList:
    def test_refresh_list_labels(self, qapp, mock_store):
        panel = MergePanel(mock_store)
        panel.add_clip("abc")
        panel.add_clip("def")
        assert panel._list.count() == 2
        item0 = panel._list.item(0)
        assert item0.data(Qt.ItemDataRole.UserRole) == "abc"


