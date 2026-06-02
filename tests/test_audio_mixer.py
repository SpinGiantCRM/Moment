"""Tests for audio_mixer.py — game + mic volume controls."""

from __future__ import annotations

import pytest

from moment.ui.widgets.audio_mixer import AudioMixer

pytestmark = [pytest.mark.gui]


class TestAudioMixerInit:
    """Tests for AudioMixer construction and defaults."""

    def test_default_volumes(self, qtbot) -> None:
        """Volumes default to 100% for both game and mic."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert mixer.game_volume() == 100
        assert mixer.mic_volume() == 100

    def test_default_not_muted(self, qtbot) -> None:
        """Neither track is muted by default."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert not mixer.is_game_muted()
        assert not mixer.is_mic_muted()

    def test_sliders_range_0_to_200(self, qtbot) -> None:
        """Both sliders have range 0–200."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert mixer._game_slider.minimum() == 0
        assert mixer._game_slider.maximum() == 200
        assert mixer._mic_slider.minimum() == 0
        assert mixer._mic_slider.maximum() == 200

    def test_value_labels_show_percent(self, qtbot) -> None:
        """Value labels show percentage with % sign."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert mixer._game_value_label.text() == "100%"
        assert mixer._mic_value_label.text() == "100%"


class TestAudioMixerSetVolumes:
    """Tests for set_volumes()."""

    def test_set_volumes_updates_internal_state(self, qtbot) -> None:
        """set_volumes updates the internal volume values."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer.set_volumes(game=150, mic=50)
        assert mixer.game_volume() == 150
        assert mixer.mic_volume() == 50

    def test_set_volumes_clamps_to_range(self, qtbot) -> None:
        """set_volumes clamps values to 0–200."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer.set_volumes(game=250, mic=-10)
        assert mixer.game_volume() == 200
        assert mixer.mic_volume() == 0

    def test_set_volumes_updates_labels(self, qtbot) -> None:
        """set_volumes updates the displayed value labels."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer.set_volumes(game=75, mic=125)
        assert mixer._game_value_label.text() == "75%"
        assert mixer._mic_value_label.text() == "125%"

    def test_set_volumes_updates_sliders(self, qtbot) -> None:
        """set_volumes moves the slider handles."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer.set_volumes(game=80, mic=60)
        assert mixer._game_slider.value() == 80
        assert mixer._mic_slider.value() == 60

    def test_set_volumes_does_not_emit(self, qtbot) -> None:
        """set_volumes does NOT emit volume_changed."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        emitted = []

        def on_change(g: int, m: int) -> None:
            emitted.append((g, m))

        mixer.volume_changed.connect(on_change)
        mixer.set_volumes(game=50, mic=50)
        assert len(emitted) == 0


class TestAudioMixerSliderInteraction:
    """Tests for slider value changes."""

    def test_game_slider_emits_volume_changed(self, qtbot) -> None:
        """Moving the game slider emits volume_changed."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        with qtbot.waitSignal(mixer.volume_changed, timeout=1000) as blocker:
            mixer._game_slider.setValue(120)

        assert blocker.args == [120, 100]  # game=120, mic=100

    def test_mic_slider_emits_volume_changed(self, qtbot) -> None:
        """Moving the mic slider emits volume_changed."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        with qtbot.waitSignal(mixer.volume_changed, timeout=1000) as blocker:
            mixer._mic_slider.setValue(75)

        assert blocker.args == [100, 75]  # game=100, mic=75

    def test_slider_updates_value_label(self, qtbot) -> None:
        """Slider value change updates the percentage label."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer._game_slider.setValue(42)
        assert mixer._game_value_label.text() == "42%"

    def test_both_sliders_independent(self, qtbot) -> None:
        """Game and mic sliders operate independently."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer._game_slider.setValue(10)
        mixer._mic_slider.setValue(190)
        assert mixer.game_volume() == 10
        assert mixer.mic_volume() == 190


class TestAudioMixerMute:
    """Tests for mute toggle buttons."""

    def test_game_mute_toggle(self, qtbot) -> None:
        """Toggling game mute sets is_game_muted."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert not mixer.is_game_muted()
        mixer._toggle_game_mute()
        assert mixer.is_game_muted()
        mixer._toggle_game_mute()
        assert not mixer.is_game_muted()

    def test_mic_mute_toggle(self, qtbot) -> None:
        """Toggling mic mute sets is_mic_muted."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        assert not mixer.is_mic_muted()
        mixer._toggle_mic_mute()
        assert mixer.is_mic_muted()
        mixer._toggle_mic_mute()
        assert not mixer.is_mic_muted()

    def test_game_mute_changes_button_text(self, qtbot) -> None:
        """Muting game audio changes the button icon."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        original = mixer._game_mute_btn.text()
        mixer._toggle_game_mute()
        assert mixer._game_mute_btn.text() != original
        mixer._toggle_game_mute()
        assert mixer._game_mute_btn.text() == original

    def test_mic_mute_changes_button_text(self, qtbot) -> None:
        """Muting mic audio changes the button icon."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        original = mixer._mic_mute_btn.text()
        mixer._toggle_mic_mute()
        assert mixer._mic_mute_btn.text() != original
        mixer._toggle_mic_mute()
        assert mixer._mic_mute_btn.text() == original

    def test_mute_emits_volume_changed(self, qtbot) -> None:
        """Toggling mute emits volume_changed."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        with qtbot.waitSignal(mixer.volume_changed, timeout=1000) as blocker:
            mixer._toggle_game_mute()

        # When muted, effective game volume is 0
        assert blocker.args == [0, 100]

    def test_muted_volume_zero_even_if_slider_high(self, qtbot) -> None:
        """Effective volume is 0 when muted, regardless of slider position."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer._game_slider.setValue(200)
        mixer._toggle_game_mute()

        with qtbot.waitSignal(mixer.volume_changed, timeout=1000) as blocker:
            mixer._game_slider.setValue(150)

        # Game is still muted, so effective volume is 0
        assert blocker.args == [0, 100]

    def test_unmute_restores_effective_volume(self, qtbot) -> None:
        """Unmuting restores the effective volume to the slider value."""
        mixer = AudioMixer()
        qtbot.addWidget(mixer)

        mixer._game_slider.setValue(150)
        mixer._toggle_game_mute()  # mute
        mixer._toggle_game_mute()  # unmute

        with qtbot.waitSignal(mixer.volume_changed, timeout=1000) as blocker:
            mixer._game_slider.setValue(130)

        assert blocker.args == [130, 100]
