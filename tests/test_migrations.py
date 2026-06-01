"""Tests for core/migrations.py — legacy JSON import and directory migration."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.models import Clip
from moment.core.migrations import (
    OLD_JSON_PATH,
    migrate_from_json,
    migrate_old_dirs,
)
pytestmark = [pytest.mark.integration]


class TestMigrateOldDirs:
    def test_renames_when_old_exists_new_does_not(self, tmp_path: Path) -> None:
        old = tmp_path / "old-dir"
        new = tmp_path / "new-dir"
        old.mkdir(parents=True)

        migrate_old_dirs(
            old_db_dir=str(old),
            old_data_dir=str(old),
            new_db_dir=str(new),
            new_data_dir=str(new),
        )

        assert not old.exists()
        assert new.is_dir()

    def test_skips_when_new_already_exists(self, tmp_path: Path) -> None:
        old = tmp_path / "old-dir2"
        new = tmp_path / "new-dir2"
        old.mkdir(parents=True)
        new.mkdir(parents=True)

        migrate_old_dirs(
            old_db_dir=str(old),
            old_data_dir=str(new),  # data is the same
            new_db_dir=str(new),
            new_data_dir=str(new),
        )

        # Old should still exist since new already exists
        assert old.is_dir()
        assert new.is_dir()

    def test_handles_rename_oserror(self, tmp_path: Path) -> None:
        old = tmp_path / "old-dir3"
        new = tmp_path / "new-dir3"
        old.mkdir(parents=True)

        with patch("os.rename", side_effect=OSError("permission denied")):
            migrate_old_dirs(
                old_db_dir=str(old),
                old_data_dir=str(old),
                new_db_dir=str(new),
                new_data_dir=str(new),
            )
            # Old should still exist since rename failed
            assert old.is_dir()

class TestMigrateFromJson:
    def test_no_file_returns_zero(self, store, tmp_path: Path) -> None:
        """When old_path doesn't exist, returns 0."""

        result = migrate_from_json(store, tmp_path / "nonexistent.json")
        assert result == 0

    def test_db_has_data_renames_to_bak(self, store, tmp_path: Path) -> None:
        """When DB already has data, renames JSON to .bak."""
        json_path = tmp_path / "clips.json"
        json_path.write_text("[]")

        # Insert a real clip so the DB has data (COUNT > 0)
        clip = Clip(id="has-data-test", stem="pre-existing", source_path=Path("/tmp/test.mkv"), duration=10.0)
        store.insert_clip(clip)

        result = migrate_from_json(store, json_path)
        assert result == 0
        assert not json_path.exists()  # renamed to .bak
        assert json_path.with_suffix(".json.bak").exists()

    def test_invalid_json_returns_zero(self, store, tmp_path: Path) -> None:
        """When JSON is unparseable, returns 0."""
        json_path = tmp_path / "clips.json"
        json_path.write_text("not valid json")

        # DB is empty (COUNT = 0), so migrate_from_json proceeds to parse the JSON
        result = migrate_from_json(store, json_path)
        assert result == 0

    def test_imports_clips_from_json(self, store, tmp_path: Path) -> None:
        """Happy path: imports clips from JSON array."""
        json_path = tmp_path / "clips.json"
        data = [
            {
                "id": str(uuid.uuid4()),
                "stem": "clip1",
                "source_path": "/tmp/clip1.mkv",
                "duration": 30.0,
                "file_size": 1000000,
                "title": "Test Clip",
                "game": "cs2",
            },
        ]
        json_path.write_text(json.dumps(data))

        result = migrate_from_json(store, json_path)
        assert result == 1

    def test_imports_from_legacy_dict_format(self, store, tmp_path: Path) -> None:
        """Also handles legacy format where JSON is a dict with 'clips' key."""
        json_path = tmp_path / "clips.json"
        data = {"clips": [{"stem": "legacy_clip", "source_path": "/tmp/legacy.mkv", "duration": 15.0}]}
        json_path.write_text(json.dumps(data))

        result = migrate_from_json(store, json_path)
        assert result >= 1

    def test_skips_corrupt_entries(self, store, tmp_path: Path) -> None:
        """Corrupt entries in JSON are skipped gracefully."""
        json_path = tmp_path / "clips.json"
        data = [
            {"bad_entry": "missing fields"},
            {"stem": "good_clip", "source_path": "/tmp/good.mkv", "duration": 10.0},
        ]
        json_path.write_text(json.dumps(data))

        result = migrate_from_json(store, json_path)
        assert result >= 1  # good entry was imported

    def test_bak_rename_failure_not_fatal(self, store, tmp_path: Path) -> None:
        """If renaming to .bak fails, the migration still returns the count."""
        json_path = tmp_path / "clips.json"
        json_path.write_text("[]")

        with patch("os.rename", side_effect=OSError("read-only filesystem")):
            result = migrate_from_json(store, json_path)
            assert result == 0  # empty array, no clips imported


