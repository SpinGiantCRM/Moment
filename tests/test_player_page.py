"""Tests for pages/player_page.py — player with transport overlay, seek bar, metadata."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from moment.ui.pages.player_page import PlayerPage, SeekBar, _fmt_ms, _fmt_size

pytestmark = [pytest.mark.gui]


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
    """Tests for the custom-painted seek bar widget."""

    def test_create(self, qapp) -> None:
        bar = SeekBar()
        assert bar is not None

    def test_initial_duration(self, qapp) -> None:
        bar = SeekBar()
        assert bar._duration_ms == 0

    def test_set_duration(self, qapp) -> None:
        bar = SeekBar()
        bar.set_duration(125000)
        assert bar._duration_ms == 125000

    def test_set_position(self, qapp) -> None:
        bar = SeekBar()
        bar.set_duration(300000)
        bar.set_position(150000)
        assert bar._position_ms == 150000

    def test_seek_on_click(self, qapp) -> None:
        bar = SeekBar()
        bar.set_duration(100000)
        bar.setFixedWidth(300)
        # Simulate a click at ~75% of the track
        # Track runs from 44+4=48 to 300-44-4=252; 75% = 48+0.75*204=201
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import Qt
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(201, 12),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        bar.mousePressEvent(event)
        # Position should be ~75% of duration
        assert 70000 <= bar._position_ms <= 80000

    def test_enter_leave_hover(self, qapp) -> None:
        bar = SeekBar()
        assert not bar._hovering
        assert not bar._thumb_visible
        bar.enterEvent(None)
        assert bar._hovering
        assert bar._thumb_visible
        bar.leaveEvent(None)
        assert not bar._hovering
        assert not bar._thumb_visible

    def test_minimum_height(self, qapp) -> None:
        bar = SeekBar()
        assert bar.minimumHeight() == SeekBar.HIT_HEIGHT


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
        assert page._skip_back_btn is not None
        assert page._skip_fwd_btn is not None
        assert page._volume_slider is not None
        assert page._fullscreen_btn is not None
        assert page._empty_state is not None
        assert page._title_label is not None
        assert page._info_label is not None
        assert page._share_btn is not None
        assert page._download_btn is not None
        assert page._edit_btn is not None
        assert page._delete_btn is not None

    def test_empty_state_visible_by_default(self, page: PlayerPage) -> None:
        assert not page._empty_state.isHidden()
        assert page._video_widget.isHidden()
        assert page._meta_section.isHidden()

    def test_player_stopped_initially(self, page: PlayerPage) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer
        assert page._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState

    def test_signals_exist(self, qapp) -> None:
        page = PlayerPage()
        assert hasattr(page, "back_requested")
        assert hasattr(page, "fullscreen_toggled")
        assert hasattr(page, "share_requested")
        assert hasattr(page, "download_requested")
        assert hasattr(page, "edit_requested")
        assert hasattr(page, "delete_requested")

    def test_controls_visible_initially(self, qapp) -> None:
        page = PlayerPage()
        assert page._controls_visible

    def test_hide_timer_exists(self, qapp) -> None:
        page = PlayerPage()
        assert page._hide_timer is not None
        assert page._hide_timer.interval() == 3000


class TestPlayerPageControls:
    """Tests for transport controls behavior."""

    def test_show_controls_cancels_timer(self, qapp) -> None:
        page = PlayerPage()
        page._hide_timer.start()
        assert page._hide_timer.isActive()
        page._show_controls()
        # Timer should be stopped
        assert not page._hide_timer.isActive()
        assert page._controls_visible

    def test_fade_out_controls_while_playing(self, qapp) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer
        page = PlayerPage()
        # Simulate playing state
        page._player.playbackState = MagicMock(
            return_value=QMediaPlayer.PlaybackState.PlayingState
        )
        page._controls_visible = True
        page._fade_out_controls()
        assert not page._controls_visible

    def test_update_play_icon(self, qapp) -> None:
        page = PlayerPage()
        page._update_play_icon("play")
        # Should have set the icon (we just check no crash)
        assert page._play_btn is not None

    def test_toggle_mute(self, qapp) -> None:
        page = PlayerPage()
        was_muted = page._audio_output.isMuted()
        page._toggle_mute()
        assert page._audio_output.isMuted() != was_muted

    def test_skip_back(self, qapp) -> None:
        page = PlayerPage()
        page._player.position = MagicMock(return_value=30000)
        page._player.setPosition = MagicMock()
        page._skip_back()
        page._player.setPosition.assert_called_once_with(20000)

    def test_skip_forward(self, qapp) -> None:
        page = PlayerPage()
        page._player.position = MagicMock(return_value=30000)
        page._player.duration = MagicMock(return_value=120000)
        page._player.setPosition = MagicMock()
        page._skip_forward()
        page._player.setPosition.assert_called_once_with(40000)


class TestPlayerPageLoad:
    """Tests for load_clip() method."""

    def test_load_clip_no_store(self, qapp) -> None:
        page = PlayerPage()
        page.load_clip("any-id")  # should not raise

    def test_load_clip_not_found(self, qapp) -> None:
        """Empty label shown when _on_data_ready receives None."""
        page = PlayerPage()
        page._on_data_ready(None)
        assert not page._empty_state.isHidden()

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

        page._on_data_ready(clip)

        page._player.stop.assert_called_once()
        page._player.play.assert_called_once()
        assert page._empty_state.isHidden()
        assert not page._video_widget.isHidden()
        assert not page._meta_section.isHidden()

    def test_load_clip_metadata(self, qapp) -> None:
        """Metadata section is populated after successful load."""
        from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility

        clip = Clip(
            id="player-2", stem="test_clip",
            source_path=__import__("pathlib").Path("/tmp/test.mkv"),
            duration=30.0, title="Test Clip", game="Valorant",
            file_size=50_000_000,
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

        page._on_data_ready(clip)

        assert page._title_label.text() == "Test Clip"
        assert "Valorant" in page._info_label.text()

    def test_load_clip_error(self, qapp) -> None:
        """Empty label shown when _on_load_error is called."""
        page = PlayerPage()
        page._on_load_error("fail")
        assert not page._empty_state.isHidden()

    def test_stop(self, qapp) -> None:
        page = PlayerPage()
        page._player.stop = MagicMock()
        page._player.setSource = MagicMock()
        page.stop()
        page._player.stop.assert_called_once()

    def test_hide_event_cancels_loader(self, qapp) -> None:
        page = PlayerPage()
        mock_loader = MagicMock()
        page._loader = mock_loader
        from PyQt6.QtGui import QHideEvent
        page.hideEvent(QHideEvent())
        mock_loader.cancel.assert_called_once()
        assert page._loader is None
