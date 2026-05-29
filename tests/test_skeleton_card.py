"""Tests for skeleton_card.py — pulse-animated placeholder card."""

from __future__ import annotations

import pytest

from PyQt6.QtGui import QColor

from moment.ui.widgets.skeleton_card import SkeletonCard, _CARD_W, _CARD_H


class TestSkeletonCardInit:
    """Tests for SkeletonCard construction and defaults."""

    def test_create(self, qtbot) -> None:
        """SkeletonCard can be created."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        assert card.width() == _CARD_W
        assert card.height() == _CARD_H

    def test_animation_running_by_default(self, qtbot) -> None:
        """Opacity animation starts running automatically."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        assert card._anim.state() == card._anim.State.Running

    def test_default_opacity(self, qtbot) -> None:
        """Opacity starts between 0.3 and 1.0 (animation may have started)."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        # QPropertyAnimation may set startValue (0.3) immediately on start()
        assert 0.0 <= card._opacity_val <= 1.01

    def test_opacity_property_attenuates(self, qtbot) -> None:
        """Setting _opacity property triggers update."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        card._opacity = 0.5
        assert card._opacity_val == 0.5

    def test_animation_range(self, qtbot) -> None:
        """Animation cycles between 0.3 and 1.0."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        assert card._anim.startValue() == 0.3
        assert card._anim.endValue() == 1.0

    def test_animation_infinite(self, qtbot) -> None:
        """Animation loops infinitely."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        assert card._anim.loopCount() == -1


class TestSkeletonCardPaint:
    """Tests for paintEvent rendering."""

    def test_paint_does_not_crash(self, qtbot) -> None:
        """paintEvent runs without errors."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        card.show()
        card.repaint()

    def test_paint_at_mid_opacity(self, qtbot) -> None:
        """paintEvent runs at mid opacity."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        card._opacity_val = 0.5
        card.show()
        card.repaint()

    def test_paint_at_zero_opacity(self, qtbot) -> None:
        """paintEvent runs at zero opacity."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        card._opacity_val = 0.0
        card.show()
        card.repaint()


class TestSkeletonCardSetColor:
    """Tests for set_color()."""

    def test_set_color_updates_base_color(self, qtbot) -> None:
        """set_color changes the base fill color."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        new_color = QColor(255, 0, 0)
        card.set_color(new_color)
        assert card._base_color == new_color

    def test_set_color_then_paint(self, qtbot) -> None:
        """Paint after set_color runs without errors."""
        card = SkeletonCard()
        qtbot.addWidget(card)
        card.set_color(QColor(100, 100, 100))
        card.show()
        card.repaint()
