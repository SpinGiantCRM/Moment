"""Tests for pages/stats_page.py — metrics dashboard with charts and recent uploads."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from moment.ui.pages.stats_page import StatsPage


@pytest.fixture
def mock_store() -> MagicMock:
    """Store returning valid aggregate stats."""
    s = MagicMock()
    s.get_aggregate_stats.return_value = {
        "total_clips": 42,
        "total_storage_bytes": 1_073_741_824,
        "uploads_today": 3,
        "uploads_this_week": 12,
        "clips_per_game": [
            {"game": "CS2", "count": 20, "storage": 500_000_000},
            {"game": "Valorant", "count": 15, "storage": 400_000_000},
        ],
        "uploads_per_day": [
            {"date": "2026-05-01", "count": 2},
            {"date": "2026-05-02", "count": 1},
        ],
        "recent_uploads": [
            {
                "id": "clip-1", "title": "Ace", "game": "CS2",
                "uploaded_at": "2026-05-28T12:00:00+00:00", "file_size": 50_000_000,
            },
        ],
    }
    return s


class TestStatsPageInit:
    """Tests for StatsPage construction."""

    def test_create_without_store(self, qapp) -> None:
        page = StatsPage()
        assert page._store is None

    def test_create_with_store(self, qapp, mock_store: MagicMock) -> None:
        page = StatsPage(store=mock_store)
        assert page._store is mock_store

    def test_widgets_exist(self, qapp) -> None:
        page = StatsPage()
        assert page._card_total is not None
        assert page._card_storage is not None
        assert page._card_today is not None
        assert page._card_week is not None
        assert page._donut_chart is not None
        assert page._bar_chart is not None
        assert page._table is not None


class TestStatsPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_populates_metrics(self, qapp, mock_store: MagicMock) -> None:
        page = StatsPage(store=mock_store)
        page.refresh()
        mock_store.get_aggregate_stats.assert_called_once()

    def test_refresh_no_store_shows_zero(self, qapp) -> None:
        """Refresh with no store shows zero state."""
        page = StatsPage(store=None)
        page.refresh()
        # Should not crash, zero state shown
        assert page._table.rowCount() == 0

    def test_refresh_store_error_shows_zero(self, qapp) -> None:
        """Refresh when store raises shows zero state gracefully."""
        store = MagicMock()
        store.get_aggregate_stats.side_effect = RuntimeError("DB down")
        page = StatsPage(store=store)
        page.refresh()
        # Should not raise, zero state shown
        assert page._table.rowCount() == 0

    def test_refresh_populates_table(self, qapp, mock_store: MagicMock) -> None:
        page = StatsPage(store=mock_store)
        page.refresh()
        assert page._table.rowCount() == 1  # one recent upload
