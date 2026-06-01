"""Tests for pages/grid_page.py — clip library grid with search, sort, batch ops."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QSize

from moment.ui.pages.grid_page import ClipFilterProxyModel, GridPage
pytestmark = [pytest.mark.gui]


def _cleanup_grid_page(page: GridPage) -> None:
    """Close and schedule a GridPage for deferred deletion."""

    page.close()
    page.deleteLater()

class TestClipFilterProxyModel:
    """Tests for the filter/sort proxy model."""

    def test_create(self, qapp) -> None:
        model = ClipFilterProxyModel()
        assert model is not None

    def test_filter_accepts_empty_text(self, qapp) -> None:
        model = ClipFilterProxyModel()
        assert model.filterAcceptsRow(0, model.index(0, 0))

    def test_set_filter_text(self, qapp) -> None:
        model = ClipFilterProxyModel()
        model.set_filter_text("test")
        assert model._filter_text == "test"

class TestGridPageInit:
    """Tests for GridPage construction."""

    def test_create_without_store(self, qapp) -> None:
        page = GridPage()
        assert page._store is None
        _cleanup_grid_page(page)

    def test_create_with_store(self, qapp) -> None:
        store = MagicMock()
        page = GridPage(store=store)
        assert page._store is store
        _cleanup_grid_page(page)

    def test_widgets_exist(self, qapp) -> None:
        page = GridPage()
        assert page._search_input is not None
        assert page._sort_combo is not None
        assert page._list_view is not None
        assert page._empty_widget is not None
        assert page._error_widget is not None
        _cleanup_grid_page(page)

    def test_initial_state_empty_hidden_list_visible(self, qapp) -> None:
        """Empty widget shown, list hidden after __init__."""
        page = GridPage()
        assert not page._empty_widget.isHidden()
        assert page._list_view.isHidden()
        _cleanup_grid_page(page)

    def test_batch_bar_hidden_by_default(self, qapp) -> None:
        page = GridPage()
        assert page._batch_bar.isHidden()
        _cleanup_grid_page(page)

class TestGridPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_no_store_shows_empty(self, qapp) -> None:
        page = GridPage()
        page.refresh()
        assert not page._empty_widget.isHidden()
        _cleanup_grid_page(page)

    def test_refresh_empty_clips(self, qapp) -> None:
        """Empty state shown when _on_data_ready receives an empty list."""
        page = GridPage()
        page._on_data_ready([])
        assert not page._empty_widget.isHidden()
        _cleanup_grid_page(page)

    def test_refresh_with_clips(self, qapp) -> None:
        """Grid populated when _on_data_ready receives clips."""
        from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility

        clip = Clip(
            id="grid-1", stem="test_clip",
            source_path=__import__("pathlib").Path("/tmp/test.mkv"),
            duration=30.0, title="Test Clip", game="CS2",
            status=ClipStatus.DONE,
            visibility=ClipVisibility.PRIVATE,
            clip_type=ClipType.VIDEO,
        )
        store = MagicMock()
        store.list_clips.return_value = [clip]

        with patch("moment.ui.widgets.clip_delegate.ClipDelegate.build_item_data",
                   return_value={"id": "grid-1", "title": "Test Clip"}), \
             patch("moment.ui.widgets.clip_delegate.ClipDelegate.paint",
                   return_value=None), \
             patch("moment.ui.widgets.clip_delegate.ClipDelegate.sizeHint",
                   return_value=QSize(260, 190)):
            page = GridPage(store=store)
            page._on_data_ready([clip])
            assert page._empty_widget.isHidden()
            assert not page._list_view.isHidden()
            _cleanup_grid_page(page)

    def test_refresh_store_error(self, qapp) -> None:
        """Error state shown when _on_load_error is called."""
        page = GridPage()
        page._on_load_error("fail")
        assert not page._error_widget.isHidden()
        _cleanup_grid_page(page)

    def test_sort_combo_has_options(self, qapp) -> None:
        page = GridPage()
        assert page._sort_combo.count() > 0
        _cleanup_grid_page(page)

    def test_search_input_placeholder(self, qapp) -> None:
        page = GridPage()
        assert "Filter" in page._search_input.placeholderText()
        _cleanup_grid_page(page)


