"""Tests for core/game_profiles.py — GameProfileManager CRUD + game-exit logic."""

from __future__ import annotations

import pytest

from moment.core.game_profiles import (
    GameProfileError,
    GameProfileManager,
)
from moment.core.models import GameProfile, ReviewCardConfig


@pytest.fixture
def mgr(store):
    """Return a GameProfileManager backed by the test store."""
    return GameProfileManager(store)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_save_and_get(self, mgr):
        profile = mgr.create_default("cs2", "Counter-Strike 2")
        mgr.save(profile)
        fetched = mgr.get("cs2")
        assert fetched is not None
        assert fetched.display_name == "Counter-Strike 2"

    def test_get_nonexistent(self, mgr):
        assert mgr.get("nonexistent") is None

    def test_list(self, mgr):
        mgr.save(mgr.create_default("a", "Game A"))
        mgr.save(mgr.create_default("b", "Game B"))
        profiles = mgr.list()
        assert len(profiles) >= 2

    def test_delete(self, mgr):
        mgr.save(mgr.create_default("xyz", "XYZ"))
        mgr.delete("xyz")
        assert mgr.get("xyz") is None

    def test_delete_nonexistent_is_noop(self, mgr):
        # Should not raise
        mgr.delete("nonexistent")

    def test_save_raises_on_empty_display_name(self, mgr):
        with pytest.raises(GameProfileError, match="display_name"):
            mgr.save(GameProfile(id="x", game_name="x", display_name=""))

    def test_save_raises_on_empty_game_name(self, mgr):
        with pytest.raises(GameProfileError, match="game_name"):
            mgr.save(GameProfile(id="x", game_name="", display_name="X"))

    def test_save_raises_on_negative_min_duration(self, mgr):
        with pytest.raises(GameProfileError, match="min_duration"):
            mgr.save(GameProfile(id="x", game_name="x", display_name="X", min_duration=-1))

    def test_save_persists_new_fields(self, mgr):
        profile = mgr.create_default("cs2", "Counter-Strike 2", min_duration=15, post_capture_action="editor")
        mgr.save(profile)
        fetched = mgr.get("cs2")
        assert fetched is not None
        assert fetched.min_duration == 15
        assert fetched.post_capture_action == "editor"

    def test_save_persists_review_card(self, mgr):
        rc = ReviewCardConfig(size="large", preview_duration=30.0)
        profile = mgr.create_default("val", "Valorant")
        profile.review_card = rc
        mgr.save(profile)
        fetched = mgr.get("val")
        assert fetched is not None
        assert fetched.review_card is not None
        assert fetched.review_card.size == "large"


# ---------------------------------------------------------------------------
# Factory + get_or_create
# ---------------------------------------------------------------------------


class TestFactory:
    def test_create_default_sets_defaults(self, mgr):
        profile = mgr.create_default("cs2")
        assert profile.game_name == "cs2"
        assert profile.display_name == "cs2"  # falls back to game_name
        assert profile.replay_duration == 30
        assert profile.capture_fps == 60
        assert profile.min_duration == 30
        assert profile.post_capture_action == "card"
        assert profile.review_card is not None

    def test_create_default_with_display_name(self, mgr):
        profile = mgr.create_default("cs2", "Counter-Strike 2")
        assert profile.display_name == "Counter-Strike 2"

    def test_get_or_create_creates(self, mgr):
        profile = mgr.get_or_create("cs2")
        assert profile is not None
        assert profile.game_name == "cs2"
        # Should now be persisted
        assert mgr.get("cs2") is not None

    def test_get_or_create_returns_existing(self, mgr):
        original = mgr.create_default("cs2", "Counter-Strike 2", min_duration=45)
        mgr.save(original)
        fetched = mgr.get_or_create("cs2")
        assert fetched.min_duration == 45  # Existing value preserved


# ---------------------------------------------------------------------------
# Game-exit flow
# ---------------------------------------------------------------------------


class TestGameExitFlow:
    def test_discard_below_threshold(self, mgr):
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="card")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=15.0)
        assert result == "discard"

    def test_card_at_threshold(self, mgr):
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="card")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=30.0)
        assert result == "card"

    def test_card_above_threshold(self, mgr):
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="card")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=45.0)
        assert result == "card"

    def test_editor_action(self, mgr):
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="editor")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=60.0)
        assert result == "editor"

    def test_discard_action_above_threshold(self, mgr):
        """post_capture_action='discard' but clip is long enough — still discard."""
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="discard")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=45.0)
        assert result == "discard"

    def test_min_duration_override(self, mgr):
        profile = mgr.create_default("cs2", min_duration=30, post_capture_action="card")
        # Override threshold to 10s — 15s clip should be kept
        result = GameProfileManager.decide_game_exit_action(
            profile, clip_duration=15.0, min_duration_override=10,
        )
        assert result == "card"

    def test_zero_second_clip(self, mgr):
        profile = mgr.create_default("cs2", min_duration=1, post_capture_action="card")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=0.0)
        assert result == "discard"

    def test_min_duration_zero_always_keeps(self, mgr):
        profile = mgr.create_default("cs2", min_duration=0, post_capture_action="card")
        result = GameProfileManager.decide_game_exit_action(profile, clip_duration=0.1)
        assert result == "card"


# ---------------------------------------------------------------------------
# Stripping input
# ---------------------------------------------------------------------------


class TestInputSanitisation:
    def test_game_name_stripped(self, mgr):
        profile = mgr.create_default("  cs2  ")
        assert profile.game_name == "cs2"

    def test_display_name_stripped(self, mgr):
        profile = mgr.create_default("cs2", "  Counter-Strike 2  ")
        assert profile.display_name == "Counter-Strike 2"
