"""Tests for the migration framework in repositories/base.py."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

pytestmark = [pytest.mark.integration]

from moment.core.repositories.base import (
    _MIGRATIONS,
    _create_schema_version_table,
    _current_schema_version,
    run_migrations,
)


class TestSchemaVersionTable:
    def test_table_created_on_first_call(self) -> None:
        """_create_schema_version_table creates the table if absent."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Verify table does not exist yet
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchall()
        assert len(tables) == 0

        _create_schema_version_table(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()
        os.unlink(db_path)

    def test_current_version_zero_on_fresh_db(self) -> None:
        """_current_schema_version returns 0 for a brand-new DB."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        ver = _current_schema_version(conn)
        assert ver == 0
        conn.close()
        os.unlink(db_path)


class TestRunMigrations:
    def test_applies_all_migrations_on_fresh_db(self) -> None:
        """run_migrations applies every migration to a brand-new DB."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        run_migrations(conn)

        ver = _current_schema_version(conn)
        assert ver == len(_MIGRATIONS)

        # Sanity-check: clips table was created
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='clips'"
        ).fetchall()
        assert len(rows) == 1
        conn.close()
        os.unlink(db_path)

    def test_idempotent(self) -> None:
        """Running migrations twice should be a no-op the second time."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        run_migrations(conn)
        ver_first = _current_schema_version(conn)

        run_migrations(conn)
        ver_second = _current_schema_version(conn)

        assert ver_first == ver_second
        assert ver_first == len(_MIGRATIONS)
        conn.close()
        os.unlink(db_path)

    def test_rollback_on_failed_migration(self) -> None:
        """A failing migration should raise and leave version unchanged."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Inject a bogus migration that will always fail
        from moment.core.repositories.base import _MIGRATIONS as _orig

        bad_migration = ("999_bad", lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
        _orig.append(bad_migration)
        try:
            with pytest.raises(RuntimeError, match="boom"):
                run_migrations(conn)

            ver = _current_schema_version(conn)
            assert ver == len(_orig) - 1  # bad one was NOT applied
        finally:
            _orig.pop()
            conn.close()
            os.unlink(db_path)

    def test_version_matches_expected_latest(self) -> None:
        """The latest migration version should equal the length of _MIGRATIONS."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        run_migrations(conn)
        ver = _current_schema_version(conn)
        assert ver == len(_MIGRATIONS)
        conn.close()
        os.unlink(db_path)


class TestMigrationDefs:
    def test_migration_list_is_ordered(self) -> None:
        """_MIGRATIONS should be ordered by version number."""
        for idx, (name, _) in enumerate(_MIGRATIONS, start=1):
            expected_prefix = f"{idx:03d}_"
            assert name.startswith(expected_prefix), (
                f"Migration {idx} name '{name}' does not start with '{expected_prefix}'"
            )

    def test_initial_migration_creates_schema(self) -> None:
        """Migration 001_initial should create all expected tables."""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Apply only the first migration
        _create_schema_version_table(conn)
        _MIGRATIONS[0][1](conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (1,))
        conn.commit()

        expected_tables = {
            "clips",
            "tags",
            "clip_tags",
            "edit_profiles",
            "bookmarks",
            "webhooks",
            "webhook_log",
            "folders",
            "game_profiles",
            "tasks",
            "url_history",
            "folder_clips",
            "rate_limits",
            "pip_cache",
            "settings",
        }
        actual = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert expected_tables <= actual, f"Missing tables: {expected_tables - actual}"
        conn.close()
        os.unlink(db_path)
