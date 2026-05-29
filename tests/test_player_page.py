"""Tests for pages/player_page.py — clip playback with controls and metadata."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from moment.ui.pages.player_page import PlayerPage, SeekBar, _fmt_ms, _fmt_size


class TestHelpers:
    """Tests for formatting helpers."""

    def test_fmt_ms_seconds(self) -> None:
        assert _fmt_ms(5000) == "0:05"

    def test_fmt_ms_minutes(self) -> None:
        assert _fmt_ms(125000) == "2:05"

    def test_fmt_ms_hours(self) -> None:
        assert _fmt_ms(3_725_000) == "1:02:05"

    def test_fmt_ms_zero(self) -> None:
        assert _fmt_ms(0) == "0:00"

    def test_fmt_size_bytes(self) -> None:
        assert "B" in _fmt_size(500)

    def test_fmt_size_kb(self) -> None:
        assert "KB" in _fmt_size(2048)

    def test_fmt_size_mb(self) -> None:
        assert "MB" in _fmt_size(5_000_000)

    def test_fmt_size_gb(self) -> None:
        assert "GB" in _fmt_size(2_000_000_000)


class TestSeekBar:
    """Tests for the custom seek bar widget."""

    def test_create(self, qapp) -> None:
        bar = SeekBar()
        assert bar is not None

    def test_initial_labels(self, qapp) -> None:
        bar = SeekBar()
        assert bar._elapsed_label.text() == "0:00"
        assert bar._total_label.text() == "0:00"

    def test_set_duration(self, qapp) -> None:
        bar = SeekBar()
        bar.set_duration(125000)
        assert bar._duration_ms == 125000
        assert bar._total_label.text() == "2:05"

    def test_set_position(self, qapp) -> None:
        bar = SeekBar()
        bar.set_duration(300000)
        bar.set_position(150000)
        assert bar._elapsed_label.text() == "2:30"


class TestPlayerPageInit:
    """Tests for PlayerPage construction."""

    @pytest.fixture
    def page(self, qapp) -> PlayerPage:
        return PlayerPage()

    def test_create_without_store(self, qapp) -> None:
        page = PlayerPage()
        assert page._store is None

    def test_create_with_store(self, qapp) -> None:
        store = MagicMock()
        page = PlayerPage(store=store)
        assert page._store is store

    def test_widgets_exist(self, page: PlayerPage) -> None:
        assert page._video_widget is not None
        assert page._player is not None
        assert page._seek_bar is not None
        assert page._play_btn is not None
        assert page._url_input is not None
        assert page._empty_label is not None

    def test_empty_state_visible_by_default(self, page: PlayerPage) -> None:
        assert not page._empty_label.isHidden()
        assert page._video_widget.isHidden()

    def test_player_stopped_initially(self, page: PlayerPage) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer
        assert page._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState


class TestPlayerPageLoad:
    """Tests for load_clip() method."""

    def test_load_clip_no_store(self, qapp) -> None:
        page = PlayerPage()
        page.load_clip("any-id")  # should not raise

    def test_load_clip_not_found(self, qapp) -> None:
        store = MagicMock()
        store.get_clip.return_value = None
        page = PlayerPage(store=store)
        page.load_clip("missing-id")
        assert not page._empty_label.isHidden()

    def test_load_clip_with_valid_data(self, qapp) -> None:
        """Load a clip with valid data — stops previous playback and sets source."""
        from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility

        clip = Clip(
            id="player-1", stem="play_clip",
            source_path=__import__("pathlib").Path("/tmp/play.mkv"),
            duration=45.0, title="Play Clip", game="CS2",
            file_size=75_000_000,
            status=ClipStatus.DONE,
            visibility=ClipVisibility.PRIVATE,
            clip_type=ClipType.VIDEO,
        )
        store = MagicMock()
        store.get_clip.return_value = clip

        page = PlayerPage(store=store)
        page._player.stop = MagicMock()
        page._player.setSource = MagicMock()
        page._player.play = MagicMock()

        page.load_clip("player-1")

        page._player.stop.assert_called_once()
        page._player.play.assert_called_once()
        assert page._empty_label.isHidden()
        assert not page._video_widget.isHidden()

    def test_load_clip_error(self, qapp) -> None:
        store = MagicMock()
        store.get_clip.side_effect = RuntimeError("fail")
        page = PlayerPage(store=store)
        page.load_clip("any-id")
        assert not page._empty_label.isHidden()
