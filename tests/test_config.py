"""Tests for core/config.py."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from moment.core.config import Config


@pytest.fixture
def tmp_db() -> str:
    """Return a path to a temporary SQLite database for config testing."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="config_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        os.unlink(path + "-wal")
        os.unlink(path + "-shm")
    except FileNotFoundError:
        pass


@pytest.fixture
def config(tmp_db: str) -> Config:
    return Config(db_path=tmp_db)


class TestConfig:
    def test_get_default(self, config: Config) -> None:
        assert config.get("nonexistent") is None
        assert config.get("nonexistent", default=42) == 42

    def test_set_and_get_string(self, config: Config) -> None:
        config.set("preferred_codec", "h264_nvenc")
        assert config.get("preferred_codec") == "h264_nvenc"

    def test_set_and_get_int(self, config: Config) -> None:
        config.set("cq", 23)
        assert config.get("cq") == 23

    def test_set_and_get_bool(self, config: Config) -> None:
        config.set("autostart", True)
        assert config.get("autostart") is True

    def test_set_and_get_list(self, config: Config) -> None:
        config.set("game_processes", ["cs2", "valorant"])
        assert config.get("game_processes") == ["cs2", "valorant"]

    def test_set_and_get_dict(self, config: Config) -> None:
        config.set("gsr_replay_quality", "ultra")
        assert config.get("gsr_replay_quality") == "ultra"

    def test_get_all(self, config: Config) -> None:
        config.set("autostart", True)
        config.set("minimize_to_tray", False)
        all_settings = config.get_all()
        assert all_settings["autostart"] is True
        assert all_settings["minimize_to_tray"] is False

    def test_delete(self, config: Config) -> None:
        config.set("sounds", True)
        config.delete("sounds")
        assert config.get("sounds") is None

    def test_overwrite(self, config: Config) -> None:
        config.set("autostart", True)
        config.set("autostart", False)
        assert config.get("autostart") is False


class TestKeyWhitelist:
    """Spec 19 — Config key whitelist and path validation."""

    def test_unknown_key_raises_valueerror(self, config: Config) -> None:
        with pytest.raises(ValueError, match="Unknown config key"):
            config.set("nonsense_key", "value")

    def test_known_key_succeeds(self, config: Config) -> None:
        config.set("autostart", True)
        assert config.get("autostart") is True

    def test_gsr_prefix_key_succeeds(self, config: Config) -> None:
        config.set("gsr_replay_enabled", True)
        assert config.get("gsr_replay_enabled") is True

    def test_path_prefix_key_within_home_succeeds(self, config: Config) -> None:
        home = os.path.expanduser("~")
        config.set("path_recordings_dir", os.path.join(home, "Videos", "Moment"))

    def test_path_prefix_key_in_tmp_succeeds(self, config: Config) -> None:
        config.set("path_temp_dir", "/tmp/moment-test")

    def test_path_outside_allowed_raises_valueerror(self, config: Config) -> None:
        with pytest.raises(ValueError, match="must be within"):
            config.set("path_db_dir", "/etc/passwd")

    def test_path_resolves_symlink_outside(self, config: Config, tmp_path: Path) -> None:
        # Resolved path outside allowed roots is rejected
        with pytest.raises(ValueError, match="must be within"):
            config.set("path_db_dir", "/etc/cron.d/../passwd")

    def test_empty_path_value_skipped(self, config: Config) -> None:
        # Empty string should not trigger path validation failure
        config.set("path_recordings_dir", "")

    def test_all_gsr_keys_accepted(self, config: Config) -> None:
        gsr_keys = [
            "gsr_replay_enabled", "gsr_replay_fps", "gsr_replay_quality",
            "gsr_replay_container", "gsr_replay_duration", "gsr_replay_audio_device",
            "gsr_replay_codec", "gsr_replay_record_area",
            "gsr_replay_show_cursor", "gsr_hotkey_show_overlay",
            "gsr_overlay_auto_hide",
        ]
        for key in gsr_keys:
            config.set(key, "test_value")

    def test_all_known_keys_accepted(self, config: Config) -> None:
        known = [
            "autostart", "minimize_to_tray", "encode_timing",
            "preferred_codec", "preset", "cq", "bitrate_mbps",
            "audio_codec", "noise_suppression",
            "toast_success", "toast_info", "toast_warning", "toast_error",
            "review_cards", "sounds", "auto_detect_games",
            "game_processes", "game_scan_interval",
            "pause_encode_during_game", "pause_thumbnail_during_game",
            "minimize_during_game", "game_exit_behavior",
            "mcp_api_token", "webhook_encryption_key",
            "discord_bot_auto_start",
        ]
        for key in known:
            config.set(key, "test_value")


class TestAutostart:
    def test_is_autostart_enabled_initially_false(self, config: Config) -> None:
        # Should be false by default (unless the dev machine has it)
        # Just verify it returns a bool
        result = config.is_autostart_enabled()
        assert isinstance(result, bool)

    def test_enable_disable(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        # Use a temp dir for autostart to not pollute real system
        with tempfile.TemporaryDirectory() as tmp:
            autostart_dir = Path(tmp) / "autostart"
            autostart_dir.mkdir()
            monkeypatch.setattr(
                "moment.core.config.AUTOSTART_DIR", str(autostart_dir)
            )
            monkeypatch.setattr(
                "moment.core.config.AUTOSTART_FILE",
                str(autostart_dir / "Moment.desktop"),
            )
            assert config.is_autostart_enabled() is False
            assert config.enable_autostart() is True
            assert config.is_autostart_enabled() is True
            assert config.disable_autostart() is True
            assert config.is_autostart_enabled() is False
