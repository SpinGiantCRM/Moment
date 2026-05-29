"""Shared pytest fixtures for Moment tests."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from moment.core.store import Store

# ---------------------------------------------------------------------------
# QApplication (session-scoped for UI tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-scoped QApplication for UI tests using offscreen platform."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def db_path() -> str:
    """Return a path to a temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="moment_test_")
    os.close(fd)
    yield path
    # Cleanup
    try:
        os.unlink(path)
        os.unlink(path + "-wal")
        os.unlink(path + "-shm")
    except FileNotFoundError:
        pass


@pytest.fixture
def store(db_path: str) -> Store:
    """Return a Store backed by a temp file database."""
    s = Store(db_path=db_path)
    yield s
    s.close()
    # Give WAL checkpoint time to flush before file cleanup by db_path fixture
    import time
    time.sleep(0.05)


@pytest.fixture
def sample_clip() -> dict:
    """Return a dict with valid Clip fields (not including id/stem which vary)."""
    return {
        "source_path": Path("/tmp/clip.mkv"),
        "recorded_at": datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        "duration": 30.5,
        "file_size": 50_000_000,
        "video_codec": "h264",
        "fps": 60.0,
        "resolution": (1920, 1080),
        "has_mic_audio": True,
        "has_game_audio": True,
        "title": "Test Clip",
        "game": "cs2",
        "tags": ["frag", "ace"],
        "favorite": False,
        "visibility": "public",
    }
