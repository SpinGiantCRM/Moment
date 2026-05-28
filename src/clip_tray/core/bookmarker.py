"""Bookmarker — manages session bookmarks for mid-session highlights.

Wraps the Store's bookmark table with convenience methods for the hotkey
daemon and editor integration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

from clip_tray.core.models import Bookmark
from clip_tray.core.store import Store

logger = logging.getLogger(__name__)


class Bookmarker:
    """Creates and retrieves session bookmarks via the Store.

    Maintains a reference to the active recording session stem so that
    callers don't need to track it externally.
    """

    def __init__(
        self,
        store: Store,
        *,
        on_bookmark_created: Callable[[Bookmark], None] | None = None,
    ) -> None:
        """Args:
            store: The application Store for persistence.
            on_bookmark_created: Optional callback invoked as
                ``callback(bookmark)`` when a bookmark is created.
        """
        self._store = store
        self._on_bookmark_created = on_bookmark_created
        self._current_session: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_session(self, stem: str) -> None:
        """Set the active recording session stem.

        Called by the recorder controller when a new replay session
        begins so that bookmarks are associated with the correct session.

        Args:
            stem: The session stem (typically the output filename without
                extension).
        """
        self._current_session = stem
        logger.debug("Active bookmark session: %s", stem)

    def create_bookmark(
        self,
        offset_seconds: float,
        label: str | None = None,
        *,
        session_stem: str | None = None,
    ) -> Bookmark | None:
        """Create a bookmark at the given offset within the active session.

        Args:
            offset_seconds: Time offset within the session (seconds).
            label: Optional human-readable label.
            session_stem: Override the active session stem.

        Returns:
            The created Bookmark, or ``None`` if no session is active.
        """
        stem = session_stem or self._current_session
        if stem is None:
            logger.warning("Cannot create bookmark: no active session")
            return None

        bm = Bookmark(
            id=str(uuid.uuid4()),
            session_stem=stem,
            offset_seconds=offset_seconds,
            label=label,
        )
        self._store.insert_bookmark(bm)
        logger.info("Bookmark created: %s @ %.1fs", stem, offset_seconds)

        if self._on_bookmark_created is not None:
            try:
                self._on_bookmark_created(bm)
            except Exception as exc:
                logger.exception("on_bookmark_created callback error: %s", exc)

        return bm

    def get_bookmarks(self, session_stem: str | None = None) -> list[Bookmark]:
        """Return all bookmarks for a session.

        Args:
            session_stem: The session to query.  Defaults to the active session.

        Returns:
            List of Bookmark objects ordered by offset_seconds.
        """
        stem = session_stem or self._current_session
        if stem is None:
            return []
        return self._store.get_bookmarks_for_session(stem)

    def delete_bookmark(self, bookmark_id: str) -> None:
        """Remove a bookmark by id."""
        self._store.delete_bookmark(bookmark_id)

    @property
    def current_session(self) -> str | None:
        """The active recording session stem, if any."""
        return self._current_session
