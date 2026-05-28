"""Configuration — settings table backed by the SQLite store.

Also manages the XDG autostart ``.desktop`` file for system launch.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser("~/.config/clip-tray")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "Moment.desktop")


class Config:
    """Key–value configuration backed by the ``settings`` table.

    The same SQLite database used by :class:`~clip_tray.core.store.Store`
    is shared.  This class only reads/writes the ``settings`` table.

    Typical usage::

        cfg = Config(store.db_path)   # or pass db_path directly
        encode_timing = cfg.get("encode_timing", default="after_game")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.path.join(CONFIG_DIR, "clips.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        # Ensure settings table exists
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------
    # Key-value access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, parsed from JSON.

        Args:
            key: Setting name.
            default: Value to return if the key is not present.

        Returns:
            The deserialized value.
        """
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is None:
                return default
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        finally:
            conn.close()

    def set(self, key: str, value: Any) -> None:
        """Persist *value* as a JSON-encoded string under *key*."""
        serialised = json.dumps(value)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, serialised),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all(self) -> dict[str, Any]:
        """Return the entire settings table as a dictionary."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            result: dict[str, Any] = {}
            for r in rows:
                try:
                    result[r["key"]] = json.loads(r["value"])
                except (json.JSONDecodeError, TypeError):
                    result[r["key"]] = r["value"]
            return result
        finally:
            conn.close()

    def delete(self, key: str) -> None:
        """Remove a setting."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Autostart
    # ------------------------------------------------------------------

    @staticmethod
    def enable_autostart() -> bool:
        """Write the ``Moment.desktop`` file into the XDG autostart directory.

        Returns:
            ``True`` on success.
        """
        desktop_content = _autostart_desktop_content()
        try:
            os.makedirs(AUTOSTART_DIR, exist_ok=True)
            Path(AUTOSTART_FILE).write_text(desktop_content)
            os.chmod(AUTOSTART_FILE, 0o755)
            logger.info("Autostart enabled: %s", AUTOSTART_FILE)
            return True
        except OSError as exc:
            logger.error("Failed to enable autostart: %s", exc)
            return False

    @staticmethod
    def disable_autostart() -> bool:
        """Remove the ``Moment.desktop`` file if it exists.

        Returns:
            ``True`` whether the file existed or not (no error).
        """
        try:
            os.unlink(AUTOSTART_FILE)
            logger.info("Autostart disabled: removed %s", AUTOSTART_FILE)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.error("Failed to disable autostart: %s", exc)
            return False
        return True

    @staticmethod
    def is_autostart_enabled() -> bool:
        """Return ``True`` if the autostart desktop file is present."""
        return os.path.isfile(AUTOSTART_FILE)


# -------------------------------------------------------------------
# Desktop entry template
# -------------------------------------------------------------------

def _autostart_desktop_content() -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Moment
Comment=GPU-accelerated clip management pipeline
Exec=clip-tray
Icon=moment
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
