"""Tests for core/import_discovery.py and stem migration."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from moment.core.config import Config
from moment.core.import_discovery import (
    count_video_files,
    discover_recording_paths,
    import_recordings_from_dirs,
)
from moment.core.models import Clip
from moment.core.repositories.base import _migration_008_add_stem_column, run_migrations

pytestmark = [pytest.mark.integration]


class TestCountVideoFiles:
    def test_counts_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "a.mkv").write_bytes(b"x" * 10)
        sub = tmp_path / "nested"
        sub.mkdir()
        (sub / "b.mp4").write_bytes(b"x" * 10)
        (sub / "note.txt").write_text("skip")

        assert count_video_files(tmp_path) == 2

    def test_missing_dir_returns_zero(self, tmp_path: Path) -> None:
        assert count_video_files(tmp_path / "missing") == 0


class TestDiscoverRecordingPaths:
    def test_finds_gsr_folder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        videos = tmp_path / "Videos"
        gsr = videos / "gsr_20260530_143210"
        gsr.mkdir(parents=True)
        (gsr / "clip1.mkv").write_bytes(b"x" * 100)
        (gsr / "clip2.mkv").write_bytes(b"x" * 100)

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        candidates = discover_recording_paths()
        assert len(candidates) >= 1
        match = next(c for c in candidates if "gsr" in c["source_dir"])
        assert match["clip_count"] == 2
        assert match["clip_count_new"] == 2

    def test_subtracts_existing_clips(self, store, tmp_path: Path, monkeypatch) -> None:
        videos = tmp_path / "Videos" / "Moment"
        videos.mkdir(parents=True)
        clip_path = videos / "existing.mkv"
        clip_path.write_bytes(b"x" * 50)

        store.insert_clip(
            Clip(
                id=str(uuid.uuid4()),
                stem="existing",
                source_path=clip_path,
                recorded_at=datetime.now(timezone.utc),
                file_size=50,
            )
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        candidates = discover_recording_paths(store=store)
        moment = next(c for c in candidates if c["label"] == "Moment recordings")
        assert moment["clip_count"] == 1
        assert moment["clip_count_new"] == 0


class TestImportRecordingsFromDirs:
    def test_imports_new_clips(self, store, tmp_path: Path) -> None:
        src = tmp_path / "recordings"
        src.mkdir()
        f1 = src / "game1.mkv"
        f2 = src / "game2.mp4"
        f1.write_bytes(b"x" * 200)
        f2.write_bytes(b"x" * 300)

        imported, failed = import_recordings_from_dirs(store, [src])
        assert imported == 2
        assert failed == 0

        clips = store.list_clips(limit=10)
        stems = {c.stem for c in clips}
        assert stems == {"game1", "game2"}

    def test_continues_after_insert_failure(self, store, tmp_path: Path, monkeypatch) -> None:
        src = tmp_path / "recordings"
        src.mkdir()
        (src / "good.mkv").write_bytes(b"x" * 100)
        (src / "bad.mkv").write_bytes(b"x" * 100)

        original_insert = store.insert_clip
        fail_path = str((src / "bad.mkv").resolve())

        def flaky_insert(clip):
            if str(clip.source_path.resolve()) == fail_path:
                raise RuntimeError("simulated insert failure")
            return original_insert(clip)

        monkeypatch.setattr(store, "insert_clip", flaky_insert)

        imported, failed = import_recordings_from_dirs(store, [src])
        assert imported == 1
        assert failed == 1
        assert store.count_clips() == 1

    def test_skips_already_imported(self, store, tmp_path: Path) -> None:
        src = tmp_path / "recordings"
        src.mkdir()
        path = src / "dup.mkv"
        path.write_bytes(b"x" * 100)

        store.insert_clip(
            Clip(
                id=str(uuid.uuid4()),
                stem="dup",
                source_path=path,
                file_size=100,
            )
        )

        imported, failed = import_recordings_from_dirs(store, [src])
        assert imported == 0
        assert failed == 0
        assert store.count_clips() == 1


class TestStemMigration:
    def test_adds_and_backfills_stem_column(self) -> None:
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        conn.execute(
            """CREATE TABLE clips (
                id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            "INSERT INTO clips (id, source_path) VALUES (?, ?)",
            ("c1", "/home/user/Videos/clip-name.mkv"),
        )
        conn.commit()

        _migration_008_add_stem_column(conn)
        conn.commit()

        row = conn.execute("SELECT stem FROM clips WHERE id = 'c1'").fetchone()
        assert row["stem"] == "clip-name"

        conn.close()
        os.unlink(db_path)

    def test_run_migrations_includes_stem(self) -> None:
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        run_migrations(conn)
        rows = conn.execute("PRAGMA table_info(clips)").fetchall()
        columns = {r["name"] for r in rows}
        assert "stem" in columns

        conn.close()
        os.unlink(db_path)


class TestSetupWizardConfig:
    def test_setup_wizard_seen_key(self, db_path: str) -> None:
        cfg = Config(db_path)
        cfg.set("setup_wizard_seen", True)
        assert cfg.get("setup_wizard_seen") is True
        cfg.close()
