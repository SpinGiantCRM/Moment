"""Tests for core/store.py — encrypted DB connection (Spec 28)."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from moment.core.repositories.base import (
    _get_or_create_db_key,
)
from moment.core.repositories.base import (
    connect_encrypted as _connect_encrypted,
)
pytestmark = [pytest.mark.integration]


class TestGetOrCreateDbKey:
    def test_returns_none_no_keyring(self) -> None:
        """_get_or_create_db_key returns None when keyring is not installed."""

        with patch("builtins.__import__", side_effect=ImportError):
            result = _get_or_create_db_key()
            assert result is None

    def test_generates_and_stores_key(self) -> None:
        """_get_or_create_db_key generates a 64-char hex key and stores it."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None  # No existing key
        mock_keyring.set_password.return_value = None

        # Inject mock into sys.modules so the function's `import keyring` finds it
        with patch.dict(sys.modules, {"keyring": mock_keyring}):
            key = _get_or_create_db_key()
            assert key is not None
            key_str = key.decode()
            # 256-bit key = 64 hex chars
            assert len(key_str) == 64
            assert all(c in "0123456789abcdef" for c in key_str)
            mock_keyring.set_password.assert_called_once()

class TestConnectEncrypted:
    def test_raises_import_error_no_sqlcipher3(self) -> None:
        """_connect_encrypted raises ImportError when sqlcipher3 is missing."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # Remove sqlcipher3 from sys.modules so the import inside
            # connect_encrypted fails cleanly.
            modules = {
                "sqlcipher3": None,
                "sqlcipher3.dbapi2": None,
            }
            with patch.dict(sys.modules, modules, clear=False):
                with pytest.raises(ImportError, match="sqlcipher3"):
                    _connect_encrypted(db_path)
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass

    def test_raises_runtime_error_no_keyring(self) -> None:
        """_connect_encrypted raises RuntimeError when keyring returns None."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # Make sqlcipher3 available but keyring fail.
            mock_sqlcipher = MagicMock()
            mock_sqlcipher.connect = MagicMock(return_value=MagicMock())
            modules = {
                "sqlcipher3": MagicMock(dbapi2=mock_sqlcipher),
                "sqlcipher3.dbapi2": mock_sqlcipher,
            }
            with patch.dict(sys.modules, modules, clear=False):
                with patch(
                    "moment.core.repositories.base._get_or_create_db_key",
                    return_value=None,
                ):
                    with pytest.raises(RuntimeError, match="keyring"):
                        _connect_encrypted(db_path)
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass

class TestStoreOpensWithEncryption:
    def test_store_uses_encrypted_connect(self) -> None:
        """Store.__init__ calls _connect_encrypted, not plain sqlite3.connect."""
        from moment.core.store import Store

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with patch("moment.core.store._connect_encrypted") as mock_connect:
                mock_conn = MagicMock(spec=sqlite3.Connection)
                mock_conn.execute.return_value = MagicMock()
                mock_connect.return_value = mock_conn

                store = Store(db_path=db_path)
                # _connect_encrypted is called twice: write conn + read conn
                assert mock_connect.call_count == 2
                assert any(call.args == (db_path,) for call in mock_connect.call_args_list)
                store.close()
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass

    def test_health_check_runs_on_init(self) -> None:
        """Store.__init__ runs the encryption health-check."""
        from moment.core.store import Store

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with patch("moment.core.store._connect_encrypted") as mock_connect:
                mock_conn = MagicMock(spec=sqlite3.Connection)
                mock_conn.execute.return_value = MagicMock()
                mock_connect.return_value = mock_conn

                with patch.object(Store, "_run_encryption_health_check") as mock_check:
                    store = Store(db_path=db_path)
                    mock_check.assert_called_once()
                    store.close()
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass


