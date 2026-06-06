"""Tests for UI pages — grid_page and recording_page with mocked Store.

Uses QT_QPA_PLATFORM=offscreen to avoid display dependency.
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from moment.core.models import Clip, ClipStatus

pytestmark = [pytest.mark.gui]


@pytest.fixture
def mock_store() -> MagicMock:
    """Return a mocked Store with basic clip data."""
    store = MagicMock()
    store.list_clips.return_value = [
        Clip(
            id=f"c{i}",
            stem=f"2026-05-{i + 1:02d}_12-00-00",
            source_path=Path(f"/tmp/clip{i}.mkv"),
            duration=30.0 + i,
            file_size=10_000_000 + i * 100,
            title=f"Clip {i}",
            game="cs2",
            status=ClipStatus.DONE,
            resolution=(1920, 1080),
            fps=60.0,
        )
        for i in range(3)
    ]
    return store


# ---------------------------------------------------------------------------
# GridPage
# ---------------------------------------------------------------------------


class TestGridPage:
    def test_creates_without_crash(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        assert page is not None
        page.close()
        page.deleteLater()

    def test_refresh_empty_store(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page._on_data_ready([])
        assert not page._empty_widget.isHidden()
        page.close()
        page.deleteLater()

    def test_refresh_with_clips(self, qapp, mock_store: MagicMock) -> None:
        from moment.core.models import Clip, ClipStatus

        clip = Clip(
            id="test-id",
            stem="test_clip",
            source_path=__import__("pathlib").Path("/tmp/test.mkv"),
            duration=30.0,
            title="Test Clip",
            game="CS2",
            status=ClipStatus.DONE,
        )

        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page._on_data_ready([clip])
        assert not page._list_view.isHidden()
        page.close()
        page.deleteLater()

    def test_search_text_applies_filter(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.set_search_text("ace")
        assert page._proxy_model._filter_text == "ace"
        page.close()
        page.deleteLater()

    def test_sort_dropdown(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.set_sort("Name A–Z")
        assert page._proxy_model._sort_column == "title"
        page.close()
        page.deleteLater()

    def test_show_empty_message(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.show()
        page._show_empty("Test empty message")
        assert page._empty_widget.isVisible()
        assert not page._list_view.isVisible()
        page.close()
        page.deleteLater()

    def test_show_error_message(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.show()
        page._show_error("Test error")
        assert page._error_widget.isVisible()
        assert not page._list_view.isVisible()
        page.close()
        page.deleteLater()

    def test_empty_state_buttons_exist(self, qapp) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        assert page._empty_widget is not None
        page.close()
        page.deleteLater()


# ---------------------------------------------------------------------------
# RecordingPage
# ---------------------------------------------------------------------------


class TestRecordingPage:
    def test_creates_in_ready_state(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        assert not page.is_recording()
        assert page._status_label.text() == "Ready to record"
        page.close()
        page.deleteLater()

    def test_set_recording(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording(fps=60)
        assert page.is_recording()
        assert "Recording" in page._status_label.text()
        page.close()
        page.deleteLater()

    def test_set_ready_after_recording(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording(fps=60)
        page.set_ready()
        assert not page.is_recording()
        assert page._status_label.text() == "Ready to record"
        page.close()
        page.deleteLater()

    def test_record_button_emits_signal(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        fired: list[int] = []
        page.start_recording.connect(lambda: fired.append(1))
        page._on_record_clicked()
        assert fired == [1]
        page.close()
        page.deleteLater()

    def test_stop_button_emits_signal(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        fired: list[int] = []
        page.stop_recording.connect(lambda: fired.append(1))
        page._on_record_clicked()
        assert fired == [1]
        page.close()
        page.deleteLater()

    def test_elapsed_tick(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        page._on_elapsed_tick()
        assert page._elapsed == 1
        assert "00:01" in page._status_label.text()
        page.close()
        page.deleteLater()

    def test_pulse_timer_starts_on_record(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        assert page._pulse_timer.isActive()
        page.close()
        page.deleteLater()

    def test_pulse_timer_stops_on_ready(self, qapp) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        page.set_ready()
        assert not page._pulse_timer.isActive()
        page.close()
        page.deleteLater()


# ---------------------------------------------------------------------------
# ClipFilterProxyModel
# ---------------------------------------------------------------------------


class TestClipFilterProxyModel:
    def test_creates(self, qapp) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        assert model is not None

    def test_empty_filter_accepts_all(self, qapp) -> None:
        from PyQt6.QtCore import QModelIndex

        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        # Empty filter should accept the row
        assert model.filterAcceptsRow(0, QModelIndex())

    def test_set_filter_text(self, qapp) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        model.set_filter_text("ace")
        assert model._filter_text == "ace"

    def test_set_sort_column(self, qapp) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        model.set_sort_column("-file_size")
        assert model._sort_column == "-file_size"
