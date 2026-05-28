"""Tests for core/config.py."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from clip_tray.core.config import Config


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
        config.set("key1", "value1")
        assert config.get("key1") == "value1"

    def test_set_and_get_int(self, config: Config) -> None:
        config.set("number", 42)
        assert config.get("number") == 42

    def test_set_and_get_bool(self, config: Config) -> None:
        config.set("flag", True)
        assert config.get("flag") is True

    def test_set_and_get_list(self, config: Config) -> None:
        config.set("items", [1, 2, 3])
        assert config.get("items") == [1, 2, 3]

    def test_set_and_get_dict(self, config: Config) -> None:
        config.set("map", {"a": 1})
        assert config.get("map") == {"a": 1}

    def test_get_all(self, config: Config) -> None:
        config.set("a", 1)
        config.set("b", "two")
        all_settings = config.get_all()
        assert all_settings == {"a": 1, "b": "two"}

    def test_delete(self, config: Config) -> None:
        config.set("temp", "value")
        config.delete("temp")
        assert config.get("temp") is None

    def test_overwrite(self, config: Config) -> None:
        config.set("key", "old")
        config.set("key", "new")
        assert config.get("key") == "new"


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
                "clip_tray.core.config.AUTOSTART_DIR", str(autostart_dir)
            )
            monkeypatch.setattr(
                "clip_tray.core.config.AUTOSTART_FILE",
                str(autostart_dir / "Moment.desktop"),
            )
            assert config.is_autostart_enabled() is False
            assert config.enable_autostart() is True
            assert config.is_autostart_enabled() is True
            assert config.disable_autostart() is True
            assert config.is_autostart_enabled() is False
