"""Tests for pages/recording_page.py — recording controls."""

from __future__ import annotations

import pytest

from moment.ui.pages.recording_page import RecordingPage

pytestmark = [pytest.mark.gui]


class TestRecordingPageInit:
    """Tests for RecordingPage construction."""

    def test_create(self, qapp) -> None:
        page = RecordingPage()
        assert page is not None

    def test_default_not_recording(self, qapp) -> None:
        page = RecordingPage()
        assert not page.is_recording()

    def test_widgets_exist(self, qapp) -> None:
        page = RecordingPage()
        assert page._record_btn is not None
        assert page._status_label is not None
        assert page._mode_group is not None
        assert page._mode_group.buttons()[0].isChecked()

    def test_mode_selector_three_buttons(self, qapp) -> None:
        page = RecordingPage()
        assert len(page._mode_group.buttons()) == 3

    def test_signals_exist(self, qapp) -> None:
        page = RecordingPage()
        assert hasattr(page, "start_recording")
        assert hasattr(page, "stop_recording")
        assert hasattr(page, "save_clip")


class TestRecordingPageStates:
    """Tests for state transitions."""

    def test_set_ready(self, qapp) -> None:
        page = RecordingPage()
        page.set_recording(60)
        assert page.is_recording()
        page.set_ready()
        assert not page.is_recording()

    def test_set_recording(self, qapp) -> None:
        page = RecordingPage()
        page.set_recording(60)
        assert page.is_recording()

    def test_set_store(self, qapp) -> None:
        from unittest.mock import MagicMock
        store = MagicMock()
        page = RecordingPage()
        page.set_store(store)
        assert page._store is store
