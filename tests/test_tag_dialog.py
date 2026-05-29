"""Tests for dialogs/tag_dialog.py — tag management with autocomplete."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from moment.ui.dialogs.tag_dialog import TagDialog


class TestTagDialogInit:
    """Tests for TagDialog construction."""

    def test_create_empty(self, qapp) -> None:
        dlg = TagDialog()
        assert dlg.windowTitle() == "Manage Tags"
        assert dlg._batch_count == 1

    def test_create_with_tags(self, qapp) -> None:
        dlg = TagDialog(current_tags=["highlight", "clutch"])
        assert dlg._tag_list.count() == 2
        tags = dlg.get_tags()
        assert "highlight" in tags
        assert "clutch" in tags

    def test_create_with_all_tags(self, qapp) -> None:
        dlg = TagDialog(all_tags=["tag1", "tag2", "tag3"])
        assert dlg._all_tags == ["tag1", "tag2", "tag3"]

    def test_create_with_store(self, qapp) -> None:
        store = MagicMock()
        dlg = TagDialog(store=store)
        assert dlg._store is store

    def test_batch_count_default(self, qapp) -> None:
        dlg = TagDialog()
        assert dlg._batch_count == 1

    def test_batch_count_multi(self, qapp) -> None:
        dlg = TagDialog(batch_count=5)
        assert dlg._batch_count == 5

    def test_batch_count_negative_clamped(self, qapp) -> None:
        dlg = TagDialog(batch_count=-1)
        assert dlg._batch_count == 1


class TestTagOperations:
    """Tests for adding and removing tags."""

    def test_add_tag(self, qapp) -> None:
        dlg = TagDialog()
        dlg._add_input.setText("new_tag")
        dlg._add_tag()
        assert dlg._tag_list.count() == 1
        assert "new_tag" in dlg._all_tags

    def test_add_empty_tag_ignored(self, qapp) -> None:
        dlg = TagDialog()
        dlg._add_input.setText("  ")
        dlg._add_tag()
        assert dlg._tag_list.count() == 0

    def test_add_duplicate_tag_ignored(self, qapp) -> None:
        dlg = TagDialog(current_tags=["existing"])
        dlg._add_input.setText("existing")
        dlg._add_tag()
        assert dlg._tag_list.count() == 1  # still 1, duplicate ignored

    def test_remove_tag(self, qapp) -> None:
        dlg = TagDialog(current_tags=["keep", "remove", "keep2"])
        dlg._remove_tag("remove")
        assert dlg._tag_list.count() == 2
        assert "remove" not in dlg.get_tags()

    def test_remove_nonexistent_tag(self, qapp) -> None:
        dlg = TagDialog(current_tags=["only"])
        dlg._remove_tag("nonexistent")
        assert dlg._tag_list.count() == 1


class TestGetTags:
    """Tests for get_tags() result."""

    def test_empty_returns_empty(self, qapp) -> None:
        dlg = TagDialog()
        assert dlg.get_tags() == []

    def test_returns_all_tags(self, qapp) -> None:
        dlg = TagDialog(current_tags=["a", "b", "c"])
        assert dlg.get_tags() == ["a", "b", "c"]

    def test_order_preserved(self, qapp) -> None:
        dlg = TagDialog(current_tags=["z", "a", "m"])
        assert dlg.get_tags() == ["z", "a", "m"]


class TestTagDialogModal:
    """Tests for dialog modal behavior."""

    def test_is_modal(self, qapp) -> None:
        dlg = TagDialog()
        assert dlg.isModal()

    def test_accept_closes(self, qapp) -> None:
        dlg = TagDialog()
        dlg.accept()
        assert dlg.result() == 1

    def test_reject_closes(self, qapp) -> None:
        dlg = TagDialog()
        dlg.reject()
        assert dlg.result() == 0
