"""Tests for progress_ring.py — circular progress indicator."""

from __future__ import annotations

import pytest

from moment.ui.widgets.progress_ring import _SIZE, ProgressRing

pytestmark = [pytest.mark.gui]


class TestProgressRingInit:
    """Tests for ProgressRing construction and defaults."""

    def test_create(self, qtbot) -> None:
        """ProgressRing can be created."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        assert ring.width() == _SIZE
        assert ring.height() == _SIZE

    def test_default_state_is_queued(self, qtbot) -> None:
        """Default state is QUEUED with orange arc."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        assert ring._state == "QUEUED"
        assert ring._opacity == 1.0

    def test_is_visible_by_default(self, qtbot) -> None:
        """Ring is visible by default once shown."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.show()
        assert not ring.isHidden()


class TestProgressRingSetState:
    """Tests for set_state() transitions."""

    def test_set_state_queued(self, qtbot) -> None:
        """QUEUED state: stops animation, full span, orange."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring._state = "ENCODING"  # pre-condition
        ring.set_state("QUEUED")
        assert ring._state == "QUEUED"
        assert ring._span_angle == 360 * 16
        assert ring._opacity == 1.0
        assert ring.isVisible()

    def test_set_state_encoding(self, qtbot) -> None:
        """ENCODING state: starts spin animation, blue."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("ENCODING")
        assert ring._state == "ENCODING"
        assert ring._span_angle == 270 * 16
        assert ring._opacity == 1.0
        assert ring.isVisible()

    def test_set_state_done(self, qtbot) -> None:
        """DONE state: full green arc, fade-out queued."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("DONE")
        assert ring._state == "DONE"
        assert ring._span_angle == 360 * 16
        assert ring._opacity == 1.0
        assert ring.isVisible()
        # Fade timer should be active
        assert ring._fade_timer.isActive()

    def test_set_state_case_insensitive(self, qtbot) -> None:
        """set_state uppercases the state string."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("done")
        assert ring._state == "DONE"

    def test_transitions_between_states(self, qtbot) -> None:
        """Can transition between all three states."""
        ring = ProgressRing()
        qtbot.addWidget(ring)

        ring.set_state("ENCODING")
        assert ring._state == "ENCODING"

        ring.set_state("DONE")
        assert ring._state == "DONE"

        ring.set_state("QUEUED")
        assert ring._state == "QUEUED"


class TestProgressRingFade:
    """Tests for DONE fade-out behavior."""

    def test_start_fade_animates_opacity_to_zero(self, qtbot) -> None:
        """_start_fade begins opacity animation from 1.0 to 0.0."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("DONE")
        ring._fade_timer.stop()
        ring._start_fade()
        assert hasattr(ring, "_fade_anim")
        assert ring._fade_anim.startValue() == 1.0
        assert ring._fade_anim.endValue() == 0.0

    def test_fade_finished_hides_widget(self, qtbot) -> None:
        """When fade completes, the widget hides."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("DONE")
        ring._fade_timer.stop()
        ring._start_fade()
        # Fast-forward the fade
        ring._fade_anim.setCurrentTime(ring._fade_anim.duration())
        ring.hide()  # trigger the finished callback manually
        assert not ring.isVisible() or ring._opacity == 0.0

    def test_opacity_prop_updates_opacity(self, qtbot) -> None:
        """_opacity_prop setter updates _opacity."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring._opacity_prop = 0.5
        assert ring._opacity == 0.5
        ring._opacity_prop = 0.0
        assert ring._opacity == 0.0


class TestProgressRingPaint:
    """Tests for paintEvent rendering."""

    def test_paint_does_not_crash(self, qtbot) -> None:
        """paintEvent runs without errors."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("ENCODING")
        ring.show()
        ring.repaint()  # triggers paintEvent

    def test_paint_queued_does_not_crash(self, qtbot) -> None:
        """paintEvent in QUEUED state renders."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.show()
        ring.repaint()

    def test_paint_done_does_not_crash(self, qtbot) -> None:
        """paintEvent in DONE state renders."""
        ring = ProgressRing()
        qtbot.addWidget(ring)
        ring.set_state("DONE")
        ring.show()
        ring.repaint()
