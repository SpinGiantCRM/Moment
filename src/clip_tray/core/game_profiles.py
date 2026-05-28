"""Game profile management — CRUD + game-exit flow logic.

Wraps :class:`~clip_tray.core.store.Store` methods for game profiles and
implements the game-exit decision flow (min duration check, post-capture action).

Absolutely **no GUI imports** allowed in this module.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from clip_tray.core.models import GameProfile, ReviewCardConfig
from clip_tray.core.store import Store

logger = logging.getLogger(__name__)

# Default values for new profiles
_DEFAULT_REPLAY_DURATION = 30
_DEFAULT_CAPTURE_FPS = 60
_DEFAULT_MIN_DURATION = 30


class GameProfileError(ValueError):
    """Raised when a game profile operation is invalid (e.g. missing display_name)."""


class GameProfileManager:
    """CRUD wrapper for game profiles backed by :class:`~clip_tray.core.store.Store`.

    Typical usage::

        mgr = GameProfileManager(store)
        profile = mgr.get("cs2")
        action = mgr.decide_game_exit_action(profile, clip_duration=45.0)
    """

    def __init__(self, store: Store) -> None:
        """Args:
            store: The application store instance.
        """
        self._store = store

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, profile: GameProfile) -> GameProfile:
        """Persist a game profile (insert or update).

        Raises:
            GameProfileError: If ``display_name`` is empty.
        """
        if not profile.display_name.strip():
            raise GameProfileError("display_name must not be empty")
        if not profile.game_name.strip():
            raise GameProfileError("game_name must not be empty")
        if profile.min_duration < 0:
            raise GameProfileError("min_duration must be >= 0")
        return self._store.save_game_profile(profile)

    def get(self, game_name: str) -> GameProfile | None:
        """Return the profile for *game_name*, or ``None``."""
        return self._store.get_game_profile(game_name)

    def list(self) -> list[GameProfile]:
        """Return all stored game profiles."""
        return self._store.list_game_profiles()

    def delete(self, game_name: str) -> None:
        """Remove the profile for *game_name* (no-op if it does not exist)."""
        self._store.delete_game_profile(game_name)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    def create_default(
        self,
        game_name: str,
        display_name: str | None = None,
        *,
        replay_duration: int = _DEFAULT_REPLAY_DURATION,
        capture_fps: int = _DEFAULT_CAPTURE_FPS,
        min_duration: int = _DEFAULT_MIN_DURATION,
        post_capture_action: Literal["card", "discard", "editor"] = "card",
    ) -> GameProfile:
        """Create a new :class:`GameProfile` with sensible defaults.

        If *display_name* is omitted it defaults to *game_name*.
        """
        return GameProfile(
            id=str(uuid.uuid4()),
            game_name=game_name.strip(),
            display_name=(display_name or game_name).strip(),
            replay_duration=replay_duration,
            capture_fps=capture_fps,
            min_duration=min_duration,
            post_capture_action=post_capture_action,
            review_card=ReviewCardConfig(),
        )

    def get_or_create(self, game_name: str) -> GameProfile:
        """Return an existing profile or create a default one.

        This is the typical lookup path used by the pipeline when a new
        game is detected.
        """
        profile = self.get(game_name)
        if profile is None:
            profile = self.create_default(game_name)
            self.save(profile)
            logger.info("Auto-created game profile for %r", game_name)
        return profile

    # ------------------------------------------------------------------
    # Game-exit flow
    # ------------------------------------------------------------------

    @staticmethod
    def decide_game_exit_action(
        profile: GameProfile,
        clip_duration: float,
        *,
        min_duration_override: int | None = None,
    ) -> str:
        """Decide what to do with a clip when the game exits.

        Args:
            profile: The game's profile (contains ``min_duration`` and
                ``post_capture_action``).
            clip_duration: Actual duration of the captured clip in seconds.
            min_duration_override: If provided, use this value instead of
                the profile's ``min_duration``.

        Returns:
            One of ``"discard"``, ``"card"``, or ``"editor"``.

            * ``"discard"`` — clip is too short; discard silently.
            * ``"card"`` — show the review card popup.
            * ``"editor"`` — open directly in the editor.
        """
        threshold = (
            min_duration_override
            if min_duration_override is not None
            else profile.min_duration
        )

        if clip_duration < threshold:
            logger.debug(
                "Clip too short for %s (%.1fs < %ds threshold) → discard",
                profile.game_name, clip_duration, threshold,
            )
            return "discard"

        action = profile.post_capture_action
        logger.debug(
            "Game exit for %s: duration=%.1fs, action=%s",
            profile.game_name, clip_duration, action,
        )
        return action
