"""Tests for pages/trash_page.py — soft-deleted clip management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QSize

from moment.ui.pages.trash_page import TrashPage


@pytest.fixture
def mock_store() -> MagicMock:
    """Store returning empty trash (default)."""
    s = MagicMock()
    s.list_clips.return_value = []
    s.empty_trash.return_value = 0
    return s


class TestTrashPageInit:
    """Tests for TrashPage construction."""

    def test_create_without_store(self, qapp) -> None:
        page = TrashPage()
        assert page._store is None

    def test_create_with_store(self, qapp, mock_store: MagicMock) -> None:
        page = TrashPage(store=mock_store)
        assert page._store is mock_store

    def test_widgets_exist(self, qapp) -> None:
        page = TrashPage()
        assert page._restore_btn is not None
        assert page._delete_btn is not None
        assert page._empty_btn is not None
        assert page._list_view is not None

    def test_buttons_initially_disabled(self, qapp) -> None:
        page = TrashPage()
        assert not page._restore_btn.isEnabled()
        assert not page._delete_btn.isEnabled()


class TestTrashPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_empty_trash(self, qapp, mock_store: MagicMock) -> None:
        """Refresh shows empty state when no deleted clips."""
        page = TrashPage(store=mock_store)
        page.refresh()
        mock_store.list_clips.assert_called_once()
        assert not page._empty_widget.isHidden()

    def test_refresh_with_deleted_clips(self, qapp) -> None:
        """Refresh populates grid when deleted clips exist."""
        from datetime import datetime, timezone
        from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility

        clip = Clip(
            id="del-1", stem="deleted_clip",
            source_path=__import__("pathlib").Path("/tmp/del.mkv"),
            duration=30.0, status=ClipStatus.DONE,
            visibility=ClipVisibility.PRIVATE,
            clip_type=ClipType.VIDEO,
            deleted_at=datetime.now(timezone.utc),
        )
        store = MagicMock()
        store.list_clips.return_value = [clip]

        # Mock paint + sizeHint to avoid QListView::doItemsLayout segfault on
        # offscreen platform — the delegate calls painful clip paths that crash
        # when there is no real paint device.
        with patch("moment.ui.widgets.clip_delegate.ClipDelegate.build_item_data",
                   return_value={"id": "del-1", "title": "Deleted Clip"}), \
             patch("moment.ui.widgets.clip_delegate.ClipDelegate.paint",
                   return_value=None), \
             patch("moment.ui.widgets.clip_delegate.ClipDelegate.sizeHint",
                   return_value=QSize(260, 190)):
            page = TrashPage(store=store)
            page.refresh()
            assert page._empty_widget.isHidden()
            assert not page._list_view.isHidden()

    def test_refresh_no_store(self, qapp) -> None:
        page = TrashPage(store=None)
        page.refresh()
        assert not page._empty_widget.isHidden()

    def test_refresh_store_error(self, qapp) -> None:
        store = MagicMock()
        store.list_clips.side_effect = RuntimeError("fail")
        page = TrashPage(store=store)
        page.refresh()
        assert not page._empty_widget.isHidden()
