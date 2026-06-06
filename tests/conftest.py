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

# Force offscreen platform for all tests (prevents Wayland/X11 crashes
# in headless/CI environments when tests create QApplication).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


@pytest.fixture(autouse=True)
def _use_plain_sqlite_for_db() -> None:
    """Bypass SQLCipher + keyring for Config/Store DB access in tests.

    Production uses encrypted connections; CI runners have no keyring backend.
    Tests that exercise connect_encrypted directly import it before patching.
    """
    with (
        patch(
            "moment.core.repositories.base.connect_encrypted",
            side_effect=_make_test_conn,
        ),
        patch(
            "moment.core.store._connect_encrypted",
            side_effect=_make_test_conn,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_mcp_singletons() -> None:
    """Reset MCP module-level Store/Pipeline singletons between tests."""
    import moment.mcp.tools as mcp_tools

    mcp_tools._store = None
    if mcp_tools._pipeline is not None:
        try:
            mcp_tools._pipeline.shutdown()
        except Exception:
            pass
    mcp_tools._pipeline = None
    yield
    mcp_tools._store = None
    if mcp_tools._pipeline is not None:
        try:
            mcp_tools._pipeline.shutdown()
        except Exception:
            pass
    mcp_tools._pipeline = None


# ---------------------------------------------------------------------------
# QApplication (session-scoped for UI tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
@pytest.fixture(autouse=True)
def _redirect_log_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect logging and crash dumps away from ~/.local/share/moment."""
    log_dir = tmp_path / "logs"
    crash_dir = tmp_path / "crash"
    log_dir.mkdir(parents=True)
    crash_dir.mkdir(parents=True)

    import moment.utils.logging as logging_mod

    monkeypatch.setattr(logging_mod, "_LOG_DIR", str(log_dir))
    monkeypatch.setattr(logging_mod, "_CRASH_DIR", str(crash_dir))


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Session-scoped QApplication for UI tests using offscreen platform."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # Process pending events before session teardown to flush deferred deletions
    # and prevent segfaults during Qt's ~QGuiApplication destructor.
    app.processEvents()


def wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Poll *predicate* until it returns truthy or *timeout* elapses.

    Raises ``AssertionError`` if the condition is not met before timeout.
    """
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return
        _time.sleep(interval)
    raise AssertionError(f"condition not met before timeout ({timeout}s)")


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
            # s.close() performs a WAL checkpoint on the connection;
            # no sleep needed — the checkpoint is synchronous on Linux.


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
