"""Shared pytest fixtures for Moment tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from PyQt6.QtWidgets import QApplication

from moment.core.store import Store

# ---------------------------------------------------------------------------
# Test Fernet key for webhook tests (bypasses keyring requirement)
# ---------------------------------------------------------------------------

_TEST_FERNET = Fernet(Fernet.generate_key())


def _make_test_conn(db_path: str) -> sqlite3.Connection:
    """Create a plain SQLite connection for testing (no encryption required)."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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


@pytest.fixture(autouse=True)
def _setup_test_fernet() -> None:
    """Inject a test Fernet instance into Store's class-level cache
    before each test, so webhook encrypt/decrypt works without keyring."""
    Store._fernet_cache = _TEST_FERNET
    if Store._fernet_lock is None:
        import threading
        Store._fernet_lock = threading.Lock()


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
    """Return a Store backed by a temp file database.

    Uses a mocked ``_connect_encrypted`` to bypass the mandatory
    pysqlcipher3 requirement for test environments.
    """
    def _fresh_test_conn(path: str) -> sqlite3.Connection:
        return _make_test_conn(path)

    with patch("moment.core.store._connect_encrypted", side_effect=_fresh_test_conn):
        with patch.object(Store, "_run_encryption_health_check", return_value=None):
            s = Store(db_path=db_path)
            yield s
            s.close()
            # Give WAL checkpoint time to flush before file cleanup
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
