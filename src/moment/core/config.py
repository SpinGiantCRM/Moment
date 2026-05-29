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

CONFIG_DIR = os.path.expanduser("~/.config/moment")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "Moment.desktop")

# Default paths — used as fallbacks when no Config override is set
_PATH_DEFAULTS: dict[str, str] = {
    "db_dir": os.path.expanduser("~/.config/moment"),
    "data_dir": os.path.expanduser("~/.local/share/moment"),
    "encode_dir": os.path.expanduser("~/.local/share/moment/encoded"),
    "thumb_dir": os.path.expanduser("~/.local/share/moment/thumbnails"),
    "temp_dir": os.path.expanduser("~/.local/share/moment/temp"),
    "log_dir": os.path.expanduser("~/.local/share/moment"),
    "recordings_dir": os.path.expanduser("~/Videos/Moment"),
    "rclone_remote": "r2",
    "rclone_bucket": "moment",
    "base_url": "",
}

# GSR (GPU Screen Recorder) defaults
_GSR_DEFAULTS: dict[str, object] = {
    "replay_enabled": False,
    "replay_fps": 60,
    "replay_quality": "very_high",
    "replay_container": "mp4",
    "replay_duration": 120,
    "replay_audio_device": "",
    "replay_codec": "",  # empty = auto-detect
    "replay_record_area": "screen",
    "replay_show_cursor": True,
    "hotkey_show_overlay": "Alt+Z",
    "overlay_auto_hide": 8,
}


class Config:
    """Key–value configuration backed by the ``settings`` table.

    The same SQLite database used by :class:`~moment.core.store.Store`
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
    # Path overrides
    # ------------------------------------------------------------------

    def get_path(self, key: str) -> str:
        """Return a storage path, falling back to the hardcoded default.

        Args:
            key: One of ``db_dir``, ``data_dir``, ``encode_dir``,
                ``thumb_dir``, ``temp_dir``, ``log_dir``,
                ``recordings_dir``, ``rclone_remote``, ``rclone_bucket``,
                ``base_url``.

        Returns:
            The configured path or the hardcoded default.
        """
        default = _PATH_DEFAULTS.get(key, "")
        value = self.get(f"path_{key}", None)
        if value is not None and isinstance(value, str) and value.strip():
            return value
        return default

    def set_path(self, key: str, value: str) -> None:
        """Persist a path override.

        Args:
            key: Same keys as :meth:`get_path`.
            value: The new path value.
        """
        self.set(f"path_{key}", value)

    def reset_paths(self) -> None:
        """Remove all path overrides, restoring hardcoded defaults."""
        for key in _PATH_DEFAULTS:
            self.delete(f"path_{key}")

    # ------------------------------------------------------------------
    # GSR (GPU Screen Recorder) settings
    # ------------------------------------------------------------------

    def get_gsr_setting(self, key: str) -> object:
        """Return a GSR setting, falling back to ``_GSR_DEFAULTS``.

        Args:
            key: One of ``replay_enabled``, ``replay_fps``,
                ``replay_quality``, ``replay_container``,
                ``replay_duration``, ``replay_audio_device``,
                ``replay_codec``, ``replay_record_area``,
                ``replay_show_cursor``, ``hotkey_show_overlay``,
                ``overlay_auto_hide``.
        """
        return self.get(f"gsr_{key}", _GSR_DEFAULTS.get(key))

    def set_gsr_setting(self, key: str, value: object) -> None:
        """Persist a GSR setting."""
        self.set(f"gsr_{key}", value)

    def get_hotkey(self) -> str:
        """Return the configured overlay hotkey (default ``Alt+Z``)."""
        val = self.get_gsr_setting("hotkey_show_overlay")
        return str(val) if val else "Alt+Z"

    # ------------------------------------------------------------------
    # Autostart
    # ------------------------------------------------------------------

    @property
    def replay_enabled(self) -> bool:
        """``True`` when GSR instant replay is enabled."""
        return bool(self.get_gsr_setting("replay_enabled"))

    # ------------------------------------------------------------------
    # Encoding preferences
    # ------------------------------------------------------------------

    def get_preferred_codec(self) -> str:
        """Return the user's preferred video codec for encoding.

        Returns one of:
            ``"auto"`` (default — runs detection chain),
            ``"h264_nvenc"``, ``"hevc_nvenc"``, ``"av1_nvenc"``,
            ``"h264_vaapi"``, ``"hevc_vaapi"``, ``"av1_vaapi"``,
            ``"h264_qsv"``, ``"hevc_qsv"``, ``"av1_qsv"``,
            or ``"libx264"``.
        """
        val = self.get("preferred_codec", "auto")
        if isinstance(val, str) and val.strip():
            return val.strip()
        return "auto"

    def set_preferred_codec(self, codec: str) -> None:
        """Persist the user's preferred video codec."""
        self.set("preferred_codec", codec.strip() or "auto")
        # Clear auto-detect cache so it re-runs with potential new context
        if codec.strip() == "auto":
            from moment.utils.ffmpeg import reset_best_encoder
            reset_best_encoder()

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
    return """[Desktop Entry]
Type=Application
Name=Moment
Comment=GPU-accelerated clip management pipeline
Exec=moment
Icon=moment
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
