"""Tests for ui/editor/music_panel.py — background music configuration."""

from __future__ import annotations

from moment.ui.editor.music_panel import MusicPanel


class TestMusicPanelInit:
    """Tests for MusicPanel construction."""

    def test_create(self, qapp) -> None:
        panel = MusicPanel()
        assert panel is not None
        assert panel._music_path == ""
        assert panel._music_volume == 100
        assert panel._fade_in == 0.0
        assert panel._fade_out == 0.0
        assert panel._loop is False

    def test_default_properties(self, qapp) -> None:
        panel = MusicPanel()
        assert panel.music_path == ""
        assert panel.music_volume == 100
        assert panel.fade_in == 0.0
        assert panel.fade_out == 0.0
        assert panel.loop is False

    def test_profile_changed_signal(self, qapp) -> None:
        panel = MusicPanel()
        assert hasattr(panel, "profile_changed")


class TestMusicPanelWidgets:
    """Tests for widget existence."""

    def test_volume_slider_exists(self, qapp) -> None:
        panel = MusicPanel()
        assert panel._volume_slider is not None

    def test_path_input_exists(self, qapp) -> None:
        panel = MusicPanel()
        assert panel._path_input is not None

    def test_fade_spinboxes_exist(self, qapp) -> None:
        panel = MusicPanel()
        assert panel._fade_in_spin is not None
        assert panel._fade_out_spin is not None

    def test_loop_checkbox_exists(self, qapp) -> None:
        panel = MusicPanel()
        assert panel._loop_check is not None


class TestMusicPanelStateChanges:
    """Tests for state mutation handlers."""

    def test_volume_change(self, qapp) -> None:
        panel = MusicPanel()
        panel._on_volume(50)
        assert panel._music_volume == 50

    def test_fade_in_change(self, qapp) -> None:
        panel = MusicPanel()
        panel._on_fade_in(2.5)
        assert panel._fade_in == 2.5

    def test_fade_out_change(self, qapp) -> None:
        panel = MusicPanel()
        panel._on_fade_out(1.0)
        assert panel._fade_out == 1.0

    def test_loop_toggle(self, qapp) -> None:
        panel = MusicPanel()
        panel._on_loop(True)
        assert panel._loop is True

    def test_clear_track(self, qapp) -> None:
        panel = MusicPanel()
        panel._music_path = "/tmp/test.mp3"
        panel._on_clear()
        assert panel._music_path == ""

    def test_set_profile(self, qapp) -> None:
        panel = MusicPanel()
        panel.set_profile(
            music_path="/tmp/bgm.mp3",
            music_volume=0.5,
            fade_in=1.0,
            fade_out=2.0,
            loop=True,
        )
        assert panel.music_path == "/tmp/bgm.mp3"
        assert panel.music_volume == 50
        assert panel.fade_in == 1.0
        assert panel.fade_out == 2.0
        assert panel.loop is True
