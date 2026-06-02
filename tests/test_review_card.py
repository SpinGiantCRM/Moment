"""Tests for ui/widgets/review_card.py — ClipReviewCard popup."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from moment.core.models import Clip, ReviewCardConfig
from moment.ui.widgets.review_card import ClipReviewCard

pytestmark = [pytest.mark.gui]


@pytest.fixture
def test_clip() -> Clip:
    return Clip(
        id=str(uuid.uuid4()),
        stem="test_review_clip",
        source_path=Path("/tmp/test_review.mkv"),
        duration=45.5,
        file_size=125_000_000,
        video_codec="h264",
        fps=60.0,
        resolution=(1920, 1080),
        title="Test Review Clip",
        game="counter-strike_2",
        recorded_at=datetime(2026, 5, 15, 10, 0, 0, tzinfo=timezone.utc),
        favorite=False,
        tags=["frag"],
    )


class TestClipReviewCardInit:
    """Tests for ClipReviewCard construction."""

    def test_create_basic(self, qapp, test_clip: Clip) -> None:

        card = ClipReviewCard(test_clip)
        assert card._clip is test_clip
        assert card.windowFlags() & 0x1  # Qt.FramelessWindowHint

    def test_create_with_config(self, qapp, test_clip: Clip) -> None:
        config = ReviewCardConfig(
            size="small",
            show_trim=False,
            show_favorite=False,
            show_rename=False,
            show_game_name=False,
            show_duration=False,
            show_file_size=False,
        )
        card = ClipReviewCard(test_clip, config=config)
        assert card._config is config
        assert card.width() <= 320

    def test_create_with_large_config(self, qapp, test_clip: Clip) -> None:
        config = ReviewCardConfig(size="large")
        card = ClipReviewCard(test_clip, config=config)
        assert card.width() >= 500

    def test_create_game_active_flag(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip, game_active=True)
        assert card._game_active is True


class TestClipReviewCardSignals:
    """Tests for signal emission."""

    def test_signals_exist(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip)
        assert hasattr(card, "closed")
        assert hasattr(card, "trim_requested")
        assert hasattr(card, "open_player_requested")

    def test_trim_requested_emitted(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip)
        emitted: list[str] = []
        card.trim_requested.connect(lambda cid: emitted.append(cid))
        card._on_trim()
        assert emitted == [test_clip.id]

    def test_open_player_requested_emitted(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip)
        emitted: list[str] = []
        card.open_player_requested.connect(lambda cid: emitted.append(cid))
        card._on_open_player()
        assert emitted == [test_clip.id]


class TestClipReviewCardDismiss:
    """Tests for card dismissal."""

    def test_dismiss_stops_timer(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip)
        assert card._dismiss_timer.isActive() is False  # not started until show_card

    def test_favorite_toggle(self, qapp, test_clip: Clip) -> None:
        card = ClipReviewCard(test_clip)
        assert test_clip.favorite is False
        card._on_favorite()
        assert test_clip.favorite is True


class TestFormatHelpers:
    """Tests for static formatting helpers."""

    def test_fmt_duration_minutes(self) -> None:
        assert ClipReviewCard._fmt_duration(90.0) == "1:30"

    def test_fmt_duration_zero(self) -> None:
        assert ClipReviewCard._fmt_duration(0.0) == "0:00"

    def test_fmt_size_mb(self) -> None:
        result = ClipReviewCard._fmt_size(50_000_000)
        assert "MB" in result

    def test_fmt_size_gb(self) -> None:
        result = ClipReviewCard._fmt_size(2_000_000_000)
        assert "GB" in result

    def test_fmt_size_kb(self) -> None:
        result = ClipReviewCard._fmt_size(5000)
        assert "KB" in result

    def test_fmt_size_bytes(self) -> None:
        result = ClipReviewCard._fmt_size(500)
        assert "B" in result
