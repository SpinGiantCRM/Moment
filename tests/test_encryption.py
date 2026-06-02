"""Tests for core/encryption.py — Fernet + keyring encryption."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock, patch

import pytest

from moment.core.encryption import (
    get_or_create_fernet,
    reset_fernet_cache,
    run_health_check,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _reset_fernet() -> None:
    reset_fernet_cache()
    yield
    reset_fernet_cache()


# ---------------------------------------------------------------------------
# get_or_create_fernet
# ---------------------------------------------------------------------------


class TestGetOrCreateFernet:
    def test_get_or_create_succeeds(self) -> None:
        """Happy path: generates a Fernet key and returns a Fernet instance."""

        with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
            f = get_or_create_fernet()
            from cryptography.fernet import Fernet

            assert isinstance(f, Fernet)

    def test_get_or_create_returns_cached(self) -> None:
        """Second call returns the cached instance."""
        with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
            f = get_or_create_fernet()
            f2 = get_or_create_fernet()
            assert f is f2

    def test_raise_on_missing_keyring(self) -> None:
        """Missing keyring raises RuntimeError."""
        # Only block the 'keyring' import, not 'cryptography'
        _real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "keyring" or name.startswith("keyring."):
                raise ImportError(f"No module named '{name}'")
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with pytest.raises(RuntimeError, match="System keyring is required"):
                get_or_create_fernet()

    def test_reads_existing_key(self) -> None:
        """If a key already exists in keyring, reuses it."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = (
            "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI="
        )
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            f = get_or_create_fernet()
            assert f is not None
            mock_keyring.get_password.assert_called_once_with("moment", "webhook_encryption_key")

    def test_keyring_get_fails_raises_runtime_error(self) -> None:
        """If keyring.get_password AND set_password both fail, raises RuntimeError."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = Exception("keyring error")
        mock_keyring.set_password.side_effect = Exception("set failed")
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            with pytest.raises(RuntimeError, match="System keyring"):
                get_or_create_fernet()

    def test_keyring_set_fails_raises_runtime_error(self) -> None:
        """If keyring.set_password fails, raises RuntimeError (no ephemeral fallback)."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        mock_keyring.set_password.side_effect = Exception("set failed")
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            with pytest.raises(RuntimeError, match="System keyring"):
                get_or_create_fernet()

    def test_reset_clears_cache(self) -> None:
        with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
            f1 = get_or_create_fernet()
            reset_fernet_cache()
            f2 = get_or_create_fernet()
            assert f1 is not f2


# ---------------------------------------------------------------------------
# run_health_check
# ---------------------------------------------------------------------------


class TestRunHealthCheck:
    def test_health_check_encrypted_header(self, tmp_path) -> None:
        """If DB header is NOT plaintext SQLite, logs debug OK."""
        db_path = tmp_path / "encrypted.db"
        db_path.write_bytes(b"\x00" * 100)

        mock_keyring = MagicMock()
        with (
            patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False),
            patch("moment.core.encryption.os.path.getsize", return_value=100),
            patch("moment.core.encryption.os.path.isfile", return_value=True),
        ):
            run_health_check(str(db_path))

    def test_health_check_round_trip(self, tmp_path) -> None:
        """Happy path: keyring works, Fernet round-trip passes."""
        mock_keyring = MagicMock()
        with (
            patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False),
            patch("moment.core.encryption.os.path.isfile", return_value=False),
        ):
            # Should not raise
            run_health_check()

    def test_health_check_reports_plaintext_db(self, tmp_path) -> None:
        """If DB is plaintext SQLite, health check logs a warning."""
        db_path = tmp_path / "plaintext.db"
        db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        mock_keyring = MagicMock()
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            with patch("moment.core.encryption.os.path.getsize", return_value=100):
                run_health_check(str(db_path))

    def test_health_check_missing_keyring(self) -> None:
        """If keyring is not installed, logs warning but doesn't crash."""
        _real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "keyring" or name.startswith("keyring."):
                raise ImportError(f"No module named '{name}'")
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            # Should log warning but not raise
            run_health_check()

    def test_health_check_fernet_round_trip_fails(self) -> None:
        """If Fernet round-trip fails (e.g. bad key), raises RuntimeError."""
        mock_keyring = MagicMock()
        # Make Fernet.generate_key return a bad key
        with (
            patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False),
            patch(
                "cryptography.fernet.Fernet.decrypt",
                side_effect=Exception("decrypt failed"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Encryption health-check failed"):
                run_health_check()

    def test_health_check_empty_db_skipped(self, tmp_path) -> None:
        """Empty or non-existent DB file skips header check."""
        db_path = tmp_path / "empty.db"
        db_path.write_bytes(b"")

        mock_keyring = MagicMock()
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            run_health_check(str(db_path))

    def test_health_check_nonexistent_db_skipped(self, tmp_path) -> None:
        """Non-existent DB file skips header check (not an error)."""
        db_path = tmp_path / "nonexistent.db"

        mock_keyring = MagicMock()
        with patch.dict(sys.modules, {"keyring": mock_keyring}, clear=False):
            # Should not raise when db doesn't exist
            run_health_check(str(db_path))


# ---------------------------------------------------------------------------
# Concurrency — Fernet initialization race
# ---------------------------------------------------------------------------


class TestFernetConcurrency:
    def test_concurrent_initialization_returns_same_instance(self) -> None:
        """Multiple threads calling get_or_create_fernet() get the same instance."""
        import threading

        results: list[object] = []
        errors: list[Exception] = []

        def get_fernet() -> None:
            try:
                with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
                    f = get_or_create_fernet()
                    results.append(f)
            except Exception as e:
                errors.append(e)

        reset_fernet_cache()
        threads = [threading.Thread(target=get_fernet) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        # All should be the same instance (cached)
        first = results[0]
        for r in results[1:]:
            assert r is first

    def test_concurrent_read_does_not_block(self) -> None:
        """Once cached, concurrent reads should not block each other."""
        import threading
        import time

        call_times: list[float] = []
        lock = threading.Lock()

        with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
            # Prime the cache
            get_or_create_fernet()

            def read_fernet() -> None:
                get_or_create_fernet()
                with lock:
                    call_times.append(time.monotonic())

            threads = [threading.Thread(target=read_fernet) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All calls should complete quickly without blocking
        assert len(call_times) == 10

    def test_reset_then_concurrent_access(self) -> None:
        """After reset_fernet_cache(), concurrent calls should all get same instance."""
        import threading

        results: list[object] = []
        errors: list[Exception] = []

        def get_fernet() -> None:
            try:
                with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
                    f = get_or_create_fernet()
                    results.append(f)
            except Exception as e:
                errors.append(e)

        reset_fernet_cache()
        threads = [threading.Thread(target=get_fernet) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        first = results[0]
        for r in results[1:]:
            assert r is first

    def test_cache_reset_does_not_affect_existing_references(self) -> None:
        """Existing Fernet instances remain valid after cache reset."""
        from cryptography.fernet import Fernet

        with patch.dict(sys.modules, {"keyring": MagicMock()}, clear=False):
            f1 = get_or_create_fernet()
            reset_fernet_cache()
            f2 = get_or_create_fernet()

            # Both should be valid Fernet instances
            assert isinstance(f1, Fernet)
            assert isinstance(f2, Fernet)
            # Should be different because cache was cleared
            assert f1 is not f2

            # Both should still work for encrypt/decrypt
            ct = f1.encrypt(b"test")
            pt = f1.decrypt(ct)
            assert pt == b"test"

            ct2 = f2.encrypt(b"test")
            pt2 = f2.decrypt(ct2)
            assert pt2 == b"test"
