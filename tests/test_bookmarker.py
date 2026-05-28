"""Tests for core/bookmarker.py — session bookmark management."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from clip_tray.core.bookmarker import Bookmarker
from clip_tray.core.models import Bookmark
from clip_tray.core.store import Store


@pytest.fixture
def store() -> MagicMock:
    """Mock Store for bookmark tests."""
    s = MagicMock(spec=Store)
    return s


@pytest.fixture
def bookmarker(store: MagicMock) -> Bookmarker:
    return Bookmarker(store=store)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestSession:
    def test_no_session_initially(self, bookmarker: Bookmarker) -> None:
        assert bookmarker.current_session is None
        assert bookmarker.get_bookmarks() == []

    def test_set_session(self, bookmarker: Bookmarker) -> None:
        bookmarker.set_session("replay_20260528")
        assert bookmarker.current_session == "replay_20260528"

    def test_get_bookmarks_uses_current_session(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        bookmarker.set_session("session1")
        store.get_bookmarks_for_session.return_value = []

        result = bookmarker.get_bookmarks()
        store.get_bookmarks_for_session.assert_called_once_with("session1")
        assert result == []


# ---------------------------------------------------------------------------
# Create bookmark
# ---------------------------------------------------------------------------


class TestCreateBookmark:
    def test_create_without_session_returns_none(
        self, bookmarker: Bookmarker
    ) -> None:
        result = bookmarker.create_bookmark(10.5, label="nice shot")
        assert result is None

    def test_create_bookmark(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        bookmarker.set_session("replay_001")

        bm = bookmarker.create_bookmark(15.0, label="headshot")

        assert bm is not None
        assert bm.session_stem == "replay_001"
        assert bm.offset_seconds == 15.0
        assert bm.label == "headshot"
        store.insert_bookmark.assert_called_once()

    def test_create_bookmark_no_label(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        bookmarker.set_session("replay_001")
        bm = bookmarker.create_bookmark(5.0)

        assert bm is not None
        assert bm.label is None

    def test_create_bookmark_explicit_session(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        bm = bookmarker.create_bookmark(3.0, session_stem="override_session")

        assert bm is not None
        assert bm.session_stem == "override_session"


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_on_bookmark_created_callback(
        self, store: MagicMock
    ) -> None:
        created: list[Bookmark] = []
        bm = Bookmarker(store=store, on_bookmark_created=lambda b: created.append(b))
        bm.set_session("replay_001")

        result = bm.create_bookmark(5.0)
        assert len(created) == 1
        assert created[0] is result

    def test_callback_exception_is_handled(
        self, store: MagicMock
    ) -> None:
        def bad_callback(b: Bookmark) -> None:
            raise RuntimeError("boom")

        bm = Bookmarker(store=store, on_bookmark_created=bad_callback)
        bm.set_session("replay_001")

        # Should not raise
        result = bm.create_bookmark(5.0)
        assert result is not None


# ---------------------------------------------------------------------------
# Get / delete bookmarks
# ---------------------------------------------------------------------------


class TestGetDelete:
    def test_get_bookmarks(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        expected = [
            Bookmark(id="1", session_stem="s1", offset_seconds=5.0),
            Bookmark(id="2", session_stem="s1", offset_seconds=12.0, label="test"),
        ]
        store.get_bookmarks_for_session.return_value = expected
        bookmarker.set_session("s1")

        result = bookmarker.get_bookmarks()
        assert len(result) == 2
        assert result[0].offset_seconds == 5.0
        assert result[1].label == "test"

    def test_get_bookmarks_explicit_session(
        self, store: MagicMock, bookmarker: Bookmarker
    ) -> None:
        expected = [Bookmark(id="3", session_stem="s2", offset_seconds=1.0)]
        store.get_bookmarks_for_session.return_value = expected

        result = bookmarker.get_bookmarks(session_stem="s2")
        store.get_bookmarks_for_session.assert_called_once_with("s2")
        assert len(result) == 1

    def test_delete_bookmark(self, store: MagicMock, bookmarker: Bookmarker) -> None:
        bookmarker.delete_bookmark("bm_123")
        store.delete_bookmark.assert_called_once_with("bm_123")
