"""Tests for pages/trash_page.py — soft-deleted clip management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QSize

from moment.ui.pages.trash_page import TrashPage

pytestmark = [pytest.mark.gui]


@pytest.fixture
def mock_store() -> MagicMock:
    s = MagicMock()
    s.list_clips.return_value = []
    s.empty_trash.return_value = 0
    return s


def _cleanup_trash_page(page: TrashPage) -> None:
    """Cancel async loads and schedule TrashPage for deferred deletion."""
    page._cancel_loader()
    page.close()
    page.deleteLater()


class TestTrashPageInit:
    """Tests for TrashPage construction."""

    def test_create_without_store(self, qapp) -> None:
        page = TrashPage()
        assert page._store is None
        _cleanup_trash_page(page)

    def test_create_with_store(self, qapp, mock_store: MagicMock) -> None:
        page = TrashPage(store=mock_store)
        assert page._store is mock_store
        _cleanup_trash_page(page)

    def test_widgets_exist(self, qapp) -> None:
        page = TrashPage()
        assert page._list_view is not None
        assert page._empty_widget is not None
        _cleanup_trash_page(page)

    def test_empty_state_visible_by_default(self, qapp) -> None:
        page = TrashPage()
        assert not page._empty_widget.isHidden()
        assert page._list_view.isHidden()
        _cleanup_trash_page(page)

    def test_empty_trash_method_exists(self, qapp) -> None:
        page = TrashPage()
        assert hasattr(page, "empty_trash")
        _cleanup_trash_page(page)

    def test_signals_exist(self, qapp) -> None:
        page = TrashPage()
        assert hasattr(page, "clip_restored")
        assert hasattr(page, "clips_removed")
        _cleanup_trash_page(page)


class TestTrashPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_empty_trash(self, qapp, mock_store: MagicMock) -> None:
        page = TrashPage(store=mock_store)
        page._on_data_ready([])
        assert not page._empty_widget.isHidden()
        _cleanup_trash_page(page)

    def test_refresh_with_deleted_clips(self, qapp) -> None:
        from datetime import datetime, timezone

        from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility

        clip = Clip(
            id="del-1",
            stem="deleted_clip",
            source_path=__import__("pathlib").Path("/tmp/del.mkv"),
            duration=30.0,
            status=ClipStatus.DONE,
            visibility=ClipVisibility.PRIVATE,
            clip_type=ClipType.VIDEO,
            deleted_at=datetime.now(timezone.utc),
        )
        store = MagicMock()
        store.list_clips.return_value = [clip]

        with (
            patch(
                "moment.ui.widgets.clip_delegate.ClipDelegate.build_item_data",
                return_value={"id": "del-1", "title": "Deleted Clip"},
            ),
            patch("moment.ui.widgets.clip_delegate.ClipDelegate.paint", return_value=None),
            patch(
                "moment.ui.widgets.clip_delegate.ClipDelegate.sizeHint",
                return_value=QSize(260, 190),
            ),
        ):
            page = TrashPage(store=store)
            page._on_data_ready([clip])
            assert page._empty_widget.isHidden()
            assert not page._list_view.isHidden()
            _cleanup_trash_page(page)

    def test_refresh_no_store(self, qapp) -> None:
        page = TrashPage(store=None)
        page.refresh()
        assert not page._empty_widget.isHidden()
        _cleanup_trash_page(page)

    def test_refresh_store_error(self, qapp) -> None:
        page = TrashPage(store=MagicMock())
        page._on_load_error("fail")
        assert not page._empty_widget.isHidden()
        _cleanup_trash_page(page)
