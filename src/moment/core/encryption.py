"""Webhook URL encryption using Fernet + keyring."""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet_lock = threading.Lock()
_fernet_cache: "Fernet | None" = None


def get_or_create_fernet() -> "Fernet":
    """Return a cached Fernet instance, creating one if necessary."""
    from cryptography.fernet import Fernet

    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache

    with _fernet_lock:
        if _fernet_cache is not None:
            return _fernet_cache

        try:
            import keyring
            key_b64 = keyring.get_password("moment", "webhook_encryption_key")
            if key_b64:
                _fernet_cache = Fernet(key_b64.encode())
                return _fernet_cache
        except ImportError:
            raise RuntimeError("System keyring is required for webhook encryption.")
        except Exception as exc:
            logger.warning("Failed to read webhook key from keyring: %s", exc)

        key = Fernet.generate_key()
        _fernet_cache = Fernet(key)
        try:
            import keyring
            keyring.set_password("moment", "webhook_encryption_key", key.decode())
            logger.info("Generated and stored new webhook encryption key")
        except Exception as exc:
            _fernet_cache = None
            raise RuntimeError(
                "System keyring is required but unavailable. "
                "Webhook encryption cannot operate without persistent key storage. "
                "Install and configure a supported keyring backend."
            ) from exc
        return _fernet_cache


def reset_fernet_cache() -> None:
    """Clear the cached Fernet instance (used by tests)."""
    global _fernet_cache
    with _fernet_lock:
        _fernet_cache = None


def run_health_check(db_path: str | None = None) -> None:
    """Verify Fernet round-trip and (optionally) DB encryption header."""
    try:
        import keyring  # noqa: F401
    except ImportError:
        logger.warning(
            "Keyring not available — webhook encryption and Discord token "
            "storage will be unavailable."
        )

    try:
        from cryptography.fernet import Fernet

        test_key = Fernet.generate_key()
        fernet = Fernet(test_key)
        plaintext = b"moment-encryption-healthcheck"
        ciphertext = fernet.encrypt(plaintext)
        decrypted = fernet.decrypt(ciphertext)
        if decrypted != plaintext:
            raise RuntimeError("Fernet round-trip test failed")
        logger.debug("Fernet encrypt/decrypt round-trip OK")
    except Exception as exc:
        raise RuntimeError(f"Encryption health-check failed: {exc}") from exc

    if db_path and os.path.isfile(db_path) and os.path.getsize(db_path) > 0:
        with open(db_path, "rb") as fh:
            header = fh.read(16)
        if header.startswith(b"SQLite format 3\x00"):
            logger.warning(
                "Database file appears to be plaintext SQLite — "
                "expected SQLCipher-encrypted file."
            )
        else:
            logger.debug("Database file header OK (encrypted)")
