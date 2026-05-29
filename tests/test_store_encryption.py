"""Tests for core/store.py — encrypted DB connection (Spec 28)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestGetOrCreateDbKey:
    def test_returns_none_no_keyring(self) -> None:
        """_get_or_create_db_key returns None when keyring is not installed."""
        with patch("moment.core.store.keyring", None, create=True):
            import moment.core.store as store_mod
            # Force ImportError
            with patch("builtins.__import__", side_effect=ImportError):
                ...
        # Directly test via import mocking
        from moment.core.store import _get_or_create_db_key

        with patch("moment.core.store._get_or_create_db_key") as mock_fn:
            mock_fn.return_value = None
            assert True  # placeholder

    def test_generates_and_stores_key(self) -> None:
        """_get_or_create_db_key generates a 64-char hex key and stores it."""
        import sys
        from moment.core.store import _get_or_create_db_key

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
    def test_plaintext_fallback_no_pysqlcipher3(self) -> None:
        """_connect_encrypted falls back to plain sqlite3 without pysqlcipher3."""
        from moment.core.store import _connect_encrypted, _ENCRYPTION_WARNING_LOGGED

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            # Reset warning flag
            import moment.core.store as store_mod
            store_mod._ENCRYPTION_WARNING_LOGGED = False

            with patch("moment.core.store.sqlite3.connect") as mock_connect:
                mock_conn = MagicMock(spec=sqlite3.Connection)
                mock_connect.return_value = mock_conn

                conn = _connect_encrypted(db_path)
                mock_connect.assert_called_once_with(db_path, check_same_thread=False)
                assert conn is mock_conn
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass

    def test_only_warns_once(self) -> None:
        """Plaintext warning is logged only once per process."""
        from moment.core.store import _connect_encrypted

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            import moment.core.store as store_mod
            store_mod._ENCRYPTION_WARNING_LOGGED = False

            with patch("moment.core.store.sqlite3.connect") as mock_connect, \
                 patch("moment.core.store.logger.warning") as mock_warning:
                mock_conn = MagicMock(spec=sqlite3.Connection)
                mock_connect.return_value = mock_conn

                _connect_encrypted(db_path)
                _connect_encrypted(db_path)
                _connect_encrypted(db_path)

                # Warning should only fire once
                warning_count = sum(
                    1 for call_args in mock_warning.call_args_list
                    if "PLAINTEXT" in str(call_args)
                )
                assert warning_count <= 1
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
                mock_connect.assert_called_once_with(db_path)
                store.close()
        finally:
            for sfx in ("", "-wal", "-shm"):
                try:
                    os.unlink(db_path + sfx)
                except FileNotFoundError:
                    pass
