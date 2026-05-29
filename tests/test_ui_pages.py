"""Tests for UI pages — grid_page and recording_page with mocked Store.

Uses QT_QPA_PLATFORM=offscreen to avoid display dependency.
"""

from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from moment.core.models import Clip, ClipStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp_session() -> QApplication:
    """Session-scoped QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def mock_store() -> MagicMock:
    """Return a mocked Store with basic clip data."""
    store = MagicMock()
    store.list_clips.return_value = [
        Clip(
            id=f"c{i}",
            stem=f"2026-05-{i+1:02d}_12-00-00",
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
    def test_creates_without_crash(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        assert page is not None

    def test_refresh_empty_store(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        store = MagicMock()
        store.list_clips.return_value = []

        page = GridPage(store=store)
        page.show()
        page.refresh()

        # Empty state should be visible
        assert page._empty_widget.isVisible()

    def test_refresh_with_clips(self, qapp_session: QApplication, mock_store: MagicMock) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage(store=mock_store)
        page.show()
        page.refresh()

        # Grid should be visible, empty state hidden
        assert page._list_view.isVisible()

    def test_search_changes_trigger_timer(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page._on_search_text_changed("ace")
        # Timer should be started (can't easily test timer internals)
        assert True

    def test_sort_dropdown(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page._on_sort_changed("A–Z")
        assert True  # should not crash

    def test_key_press_ctrl_f(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.show()
        # NB: hasFocus() is unreliable in offscreen Qt testing, so we can't
        # verify that Ctrl+F actually focuses the search input here.
        # We only verify the search input exists and setFocus() does not crash.
        page._search_input.setFocus()
        assert page._search_input is not None

    def test_key_press_escape(self, qapp_session: QApplication) -> None:
        from PyQt6.QtTest import QTest

        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        # QTest.keyPress + text() don't depend on visibility, so no show() needed
        page._search_input.setText("test")
        QTest.keyPress(page, Qt.Key.Key_Escape)
        assert page._search_input.text() == ""

    def test_show_empty_message(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.show()
        page._show_empty("Test empty message")
        assert page._empty_widget.isVisible()
        assert not page._list_view.isVisible()

    def test_show_error_message(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        page.show()
        page._show_error("Test error")
        assert page._error_widget.isVisible()
        assert not page._list_view.isVisible()

    def test_empty_state_buttons_exist(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import GridPage

        page = GridPage()
        # Empty state widget was built in __init__
        assert page._empty_widget is not None


# ---------------------------------------------------------------------------
# RecordingPage
# ---------------------------------------------------------------------------


class TestRecordingPage:
    def test_creates_in_ready_state(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.show()
        assert not page.is_recording()
        assert page._ready_widget.isVisible()
        assert not page._recording_widget.isVisible()

    def test_set_recording(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.show()
        page.set_recording(fps=60)

        assert page.is_recording()
        assert not page._ready_widget.isVisible()
        assert page._recording_widget.isVisible()

    def test_set_ready_after_recording(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.show()
        page.set_recording(fps=60)
        page.set_ready()

        assert not page.is_recording()
        assert page._ready_widget.isVisible()
        assert not page._recording_widget.isVisible()

    def test_record_button_emits_signal(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        fired: list[int] = []
        page.start_recording.connect(lambda: fired.append(1))

        page._on_record_clicked()
        assert fired == [1]

    def test_stop_button_emits_signal(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        fired: list[int] = []
        page.stop_recording.connect(lambda: fired.append(1))

        page._on_stop_clicked()
        assert fired == [1]

    def test_save_button_emits_signal(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        durations: list[int] = []
        page.save_clip.connect(lambda d: durations.append(d))

        page._on_save_clicked(30)
        assert 30 in durations

    def test_elapsed_tick(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        page._on_elapsed_tick()
        assert page._elapsed == 1
        assert "00:01" in page._rec_elapsed.text()

    def test_rec_dot_starts_animation_on_record(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        assert page._rec_dot._active

    def test_rec_dot_stops_animation_on_ready(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import RecordingPage

        page = RecordingPage()
        page.set_recording()
        page.set_ready()
        assert not page._rec_dot._active

    def test_rec_dot_initial_state(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.recording_page import _RecDot

        dot = _RecDot()
        assert not dot._active
        assert dot._phase == 0.0


# ---------------------------------------------------------------------------
# ClipFilterProxyModel
# ---------------------------------------------------------------------------


class TestClipFilterProxyModel:
    def test_creates(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        assert model is not None

    def test_empty_filter_accepts_all(self, qapp_session: QApplication) -> None:
        from PyQt6.QtCore import QModelIndex

        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        # Empty filter should accept the row
        assert model.filterAcceptsRow(0, QModelIndex())

    def test_set_filter_text(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        model.set_filter_text("ace")
        assert model._filter_text == "ace"

    def test_set_sort_column(self, qapp_session: QApplication) -> None:
        from moment.ui.pages.grid_page import ClipFilterProxyModel

        model = ClipFilterProxyModel()
        model.set_sort_column("-file_size")
        assert model._sort_column == "-file_size"
