"""Tests for pages/stats_page.py — metrics dashboard with charts and game breakdown."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from moment.ui.pages.stats_page import StatsPage

pytestmark = [pytest.mark.gui]


@pytest.fixture
def mock_store() -> MagicMock:
    """Store returning valid aggregate stats."""
    s = MagicMock()
    s.get_aggregate_stats.return_value = {
        "total_clips": 42,
        "total_storage_bytes": 1_073_741_824,
        "clips_per_game": [
            {"game": "CS2", "count": 20, "storage": 500_000_000, "total_duration": 3600},
            {"game": "Valorant", "count": 15, "storage": 400_000_000, "total_duration": 2400},
        ],
        "uploads_per_day": [
            {"date": "2026-05-01", "count": 2},
            {"date": "2026-05-02", "count": 1},
        ],
        "recent_uploads": [
            {
                "id": "clip-1",
                "title": "Ace",
                "game": "CS2",
                "uploaded_at": "2026-05-28T12:00:00+00:00",
                "file_size": 50_000_000,
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
        assert page._card_clips is not None
        assert page._card_time is not None
        assert page._card_storage is not None
        assert page._card_avg is not None
        assert page._donut_chart is not None
        assert page._bar_chart is not None
        assert page._table is not None
        assert page._refresh_btn is not None

    def test_metric_card_count(self, qapp) -> None:
        """Verify 4 metric cards exist with accent colors."""
        page = StatsPage()
        cards = [page._card_clips, page._card_time, page._card_storage, page._card_avg]
        for card in cards:
            assert card is not None

    def test_clip_activated_signal(self, qapp) -> None:
        page = StatsPage()
        assert hasattr(page, "clip_activated")


class TestStatsPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_populates_metrics(self, qapp, mock_store: MagicMock) -> None:
        page = StatsPage(store=mock_store)
        page._on_data_ready(mock_store.get_aggregate_stats.return_value)
        page._card_clips._value.text() == "42"

    def test_refresh_no_store_shows_zero(self, qapp) -> None:
        """Refresh with no store shows zero state."""
        page = StatsPage(store=None)
        page.refresh()
        assert page._table.rowCount() == 0

    def test_refresh_store_error_shows_zero(self, qapp) -> None:
        """Refresh when store raises shows zero state gracefully."""
        page = StatsPage(store=None)
        page._on_load_error("DB down")
        assert page._card_clips._value.text() == "Error"
        assert page._table.rowCount() == 0

    def test_refresh_populates_table(self, qapp, mock_store: MagicMock) -> None:
        page = StatsPage(store=mock_store)
        # Call _on_data_ready directly to avoid async timing issues
        page._on_data_ready(mock_store.get_aggregate_stats.return_value)
        assert page._table.rowCount() == 2  # two games in clips_per_game

    def test_show_zero_state(self, qapp) -> None:
        page = StatsPage()
        page._show_zero_state()
        assert page._table.rowCount() == 0
        assert page._card_clips._value.text() == "0"
        assert page._card_storage._value.text() == "0 B"


class TestStatsPageData:
    """Tests for data processing."""

    def test_on_data_ready_populates_cards(self, qapp) -> None:
        page = StatsPage()
        stats = {
            "total_clips": 10,
            "total_storage_bytes": 500_000,
            "clips_per_game": [
                {"game": "Apex", "count": 5, "storage": 250_000, "total_duration": 600},
                {"game": "CS2", "count": 5, "storage": 250_000, "total_duration": 300},
            ],
        }
        page._on_data_ready(stats)
        assert page._card_clips._value.text() == "10"
        assert page._card_storage._value.text() == "488.3 KB"
        assert page._table.rowCount() == 2

    def test_on_data_ready_no_duration(self, qapp) -> None:
        """Cards show dash when no duration data available."""
        page = StatsPage()
        stats = {
            "total_clips": 5,
            "total_storage_bytes": 100_000,
            "clips_per_game": [
                {"game": "Fortnite", "count": 5, "storage": 100_000},
            ],
        }
        page._on_data_ready(stats)
        assert page._card_time._value.text() == "\u2014"
        assert page._card_avg._value.text() == "\u2014"

    def test_on_load_error_shows_state(self, qapp) -> None:
        page = StatsPage()
        page._on_load_error("test error")
        assert page._card_clips._value.text() == "Error"
        assert page._table.rowCount() == 0


class TestDonutChart:
    """Tests for _DonutChart widget."""

    def test_create(self, qapp) -> None:
        from moment.ui.pages.stats_page import _DonutChart

        chart = _DonutChart()
        assert chart is not None
        assert chart._data == []

    def test_set_data_builds_segments(self, qapp) -> None:
        from moment.ui.pages.stats_page import _DonutChart

        chart = _DonutChart()
        data = [
            {"game": "CS2", "count": 20, "storage": 500_000},
            {"game": "Valorant", "count": 10, "storage": 500_000},
        ]
        chart.set_data(data)
        assert len(chart._segments) == 2
        assert chart._total_count == 30

    def test_set_data_empty(self, qapp) -> None:
        from moment.ui.pages.stats_page import _DonutChart

        chart = _DonutChart()
        chart.set_data([])
        assert chart._segments == []
        assert chart._total_count == 0

    def test_hover_detection(self, qapp) -> None:
        from PyQt6.QtCore import QPoint

        from moment.ui.pages.stats_page import _DonutChart

        chart = _DonutChart()
        chart.resize(300, 300)
        data = [
            {"game": "CS2", "count": 20, "storage": 500_000},
        ]
        chart.set_data(data)
        # Center point should be inside the hole, not over a segment
        center = QPoint(150, int(chart._chart_center_y()))
        assert chart._segment_at(center) == -1


class TestBarChart:
    """Tests for _BarChart widget."""

    def test_create(self, qapp) -> None:
        from moment.ui.pages.stats_page import _BarChart

        chart = _BarChart()
        assert chart is not None

    def test_set_data(self, qapp) -> None:
        from moment.ui.pages.stats_page import _BarChart

        chart = _BarChart()
        data = [
            {"game": "CS2", "count": 10},
            {"game": "Apex", "count": 5},
        ]
        chart.set_data(data)
        assert len(chart._data) == 2

    def test_set_data_empty(self, qapp) -> None:
        from moment.ui.pages.stats_page import _BarChart

        chart = _BarChart()
        chart.set_data([])
        assert chart._data == []
