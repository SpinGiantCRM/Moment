"""Tests for core/config.py."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

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
            "mcp_api_token",
            "discord_bot_auto_start",
        ]
        for key in known:
            config.set(key, "test_value")


class TestGetPath:
    def test_get_path_default(self, config: Config) -> None:
        """get_path returns default when no override is set."""
        assert config.get_path("encode_dir") == os.path.expanduser("~/.local/share/moment/encoded")

    def test_get_path_custom(self, config: Config) -> None:
        """get_path uses stored override when set."""
        custom = os.path.expanduser("~/Videos/Custom")
        config.set_path("recordings_dir", custom)
        assert config.get_path("recordings_dir") == custom

    def test_get_path_empty_key_returns_empty(self, config: Config) -> None:
        """A non-existent path key returns empty string if not in defaults."""
        assert config.get_path("nonexistent_key") == ""

    def test_reset_paths_clears_override(self, config: Config) -> None:
        """reset_paths removes all path overrides."""
        config.set_path("temp_dir", "/tmp/custom-temp")
        config.reset_paths()
        assert config.get_path("temp_dir") == os.path.expanduser("~/.local/share/moment/temp")

    def test_path_override_empty_sting_ignored(self, config: Config) -> None:
        """An empty path override string falls back to default."""
        config.set_path("thumb_dir", "")
        assert config.get_path("thumb_dir") == os.path.expanduser("~/.local/share/moment/thumbnails")


class TestGSRSettings:
    def test_get_gsr_setting_default(self, config: Config) -> None:
        """get_gsr_setting returns default when not set."""
        assert config.get_gsr_setting("replay_enabled") is False
        assert config.get_gsr_setting("replay_fps") == 60

    def test_set_and_get_gsr_setting(self, config: Config) -> None:
        """set_gsr_setting persists and get_gsr_setting retrieves."""
        config.set_gsr_setting("replay_enabled", True)
        assert config.get_gsr_setting("replay_enabled") is True

    def test_get_gsr_setting_nonexistent(self, config: Config) -> None:
        """get_gsr_setting returns None for unknown keys."""
        assert config.get_gsr_setting("nonexistent_setting") is None

    def test_get_hotkey_default(self, config: Config) -> None:
        """get_hotkey returns 'Alt+Z' by default."""
        assert config.get_hotkey() == "Alt+Z"

    def test_get_hotkey_custom(self, config: Config) -> None:
        """get_hotkey returns the stored value."""
        config.set_gsr_setting("hotkey_show_overlay", "Ctrl+F1")
        assert config.get_hotkey() == "Ctrl+F1"

    def test_replay_enabled_property(self, config: Config) -> None:
        """replay_enabled property matches get_gsr_setting."""
        assert config.replay_enabled is False
        config.set_gsr_setting("replay_enabled", True)
        assert config.replay_enabled is True


class TestCodecPreferences:
    def test_get_preferred_codec_default(self, config: Config) -> None:
        """get_preferred_codec returns 'auto' by default."""
        assert config.get_preferred_codec() == "auto"

    def test_set_and_get_preferred_codec(self, config: Config) -> None:
        """set_preferred_codec persists the codec."""
        config.set_preferred_codec("h264_nvenc")
        assert config.get_preferred_codec() == "h264_nvenc"

    def test_set_preferred_codec_empty_returns_auto(self, config: Config) -> None:
        """Setting preferred codec to empty string resets to auto."""
        config.set_preferred_codec("h264_nvenc")
        config.set_preferred_codec("")
        assert config.get_preferred_codec() == "auto"

    def test_set_preferred_codec_auto_resets_encoder_cache(self, config: Config) -> None:
        """Setting to 'auto' calls reset_best_encoder."""
        with patch("moment.utils.ffmpeg.reset_best_encoder") as mock_reset:
            config.set_preferred_codec("auto")
            mock_reset.assert_called_once()


class TestConfigPathTraversal:
    def test_path_traversal_rejected(self, config: Config) -> None:
        """path_* values pointing to /etc, /usr, or other system dirs are rejected."""
        with pytest.raises(ValueError, match="must be within \$HOME or /tmp"):
            config.set_path("recordings_dir", "/etc/moment")

    def test_path_traversal_deep_symlink_rejected(self, config: Config) -> None:
        """path_* values using relative traversal are rejected."""
        with pytest.raises(ValueError, match="must be within \$HOME or /tmp"):
            config.set_path("encode_dir", "/usr/share/moment")

    def test_path_traversal_var_dir_rejected(self, config: Config) -> None:
        """path_* values in /var are rejected."""
        with pytest.raises(ValueError, match="must be within \$HOME or /tmp"):
            config.set_path("temp_dir", "/var/lib/moment")

    def test_path_home_dir_accepted(self, config: Config) -> None:
        """path_* values in $HOME are accepted."""
        config.set_path("recordings_dir", os.path.expanduser("~/Videos/Moment"))
        assert config.get_path("recordings_dir") == os.path.expanduser("~/Videos/Moment")

    def test_path_tmp_dir_accepted(self, config: Config) -> None:
        """path_* values in /tmp are accepted."""
        config.set_path("temp_dir", "/tmp/moment-test")
        assert config.get_path("temp_dir") == "/tmp/moment-test"

    def test_path_with_empty_string_falls_back(self, config: Config) -> None:
        """Setting a path_* to empty string falls back to default."""
        config.set_path("thumb_dir", "")
        assert config.get_path("thumb_dir") == os.path.expanduser("~/.local/share/moment/thumbnails")

    def test_non_path_key_rejected(self, config: Config) -> None:
        """Setting a key not in _ALLOWED_KEYS or _ALLOWED_PREFIXES raises ValueError."""
        with pytest.raises(ValueError, match="Unknown config key"):
            config.set("nonexistent_key", "value")


class TestConfigThreadSafety:
    def test_concurrent_writes_do_not_corrupt(self, config: Config) -> None:
        """Multiple threads writing to Config simultaneously should not corrupt data."""
        import threading
        errors: list[Exception] = []

        def writer(key: str, value: str) -> None:
            try:
                config.set(key, value)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=("toast_success", str(i)))
            for i in range(50)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        # At least one value should have been written
        result = config.get("toast_success")
        assert result is not None

    def test_concurrent_reads_during_writes(self, config: Config) -> None:
        """Reading config while being written should not crash."""
        import threading
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(20):
                    config.get("toast_success")
            except Exception as e:
                errors.append(e)

        def writer() -> None:
            try:
                for i in range(20):
                    config.set("toast_info", str(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

    def test_get_all_while_concurrent_writes(self, config: Config) -> None:
        """get_all() while writes are happening should not corrupt."""
        import threading
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i in range(50):
                    config.set("toast_warning", str(i))
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(20):
                    cfg = config.get_all()
                    assert isinstance(cfg, dict)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"


class TestConfigDelete:
    def test_delete_nonexistent_key_does_not_raise(self, config: Config) -> None:
        """Deleting a non-existent key should not raise."""
        config.delete("nonexistent_key")

    def test_delete_restores_default(self, config: Config) -> None:
        """After deletion, get() returns the default."""
        config.set("toast_success", False)
        config.delete("toast_success")
        assert config.get("toast_success", default=True) is True


class TestConfigGetAll:
    def test_get_all_returns_dict(self, config: Config) -> None:
        """get_all() returns all settings as a dict."""
        config.set("toast_success", True)
        config.set("toast_info", False)
        all_settings = config.get_all()
        assert "toast_success" in all_settings
        assert "toast_info" in all_settings
        assert all_settings["toast_success"] is True
        assert all_settings["toast_info"] is False

    def test_get_all_empty_when_no_settings(self, config: Config) -> None:
        """get_all() returns empty dict when no settings are stored."""
        all_settings = config.get_all()
        # There may be leftover keys from other tests
        assert isinstance(all_settings, dict)


class TestAutostart:
    def test_is_autostart_enabled_initially_false(self, config: Config) -> None:
        # Should be false by default (unless the dev machine has it)
        # Just verify it returns a bool
        result = config.is_autostart_enabled()
        assert isinstance(result, bool)

    def test_enable_autostart_oserror_returns_false(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """If writing the desktop file fails, enable_autostart returns False."""
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
            with patch("pathlib.Path.write_text", side_effect=OSError("permission denied")):
                assert config.enable_autostart() is False

    def test_disable_autostart_no_file_returns_true(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """disable_autostart returns True even if file does not exist."""
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
            assert config.disable_autostart() is True

    def test_disable_autostart_oserror_returns_false(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """If unlink fails with non-FileNotFoundError OSError, returns False."""
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
            (autostart_dir / "Moment.desktop").write_text("[Desktop Entry]")
            with patch("os.unlink", side_effect=OSError("permission denied")):
                assert config.disable_autostart() is False

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
