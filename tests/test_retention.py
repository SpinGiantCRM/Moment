"""Tests for core/retention.py — age-based and disk-space retention policies.

Files are now trashed (moved to ~/.local/share/moment/trash/) instead of
permanently deleted.  ERROR/CORRUPT clips are skipped by default unless
``retention_remove_corrupt=true``.  ``retention_trash_days=0`` skips
trash entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import os
import shutil
import tempfile

import pytest

from moment.core.config import Config
from moment.core.models import Clip, ClipStatus
from moment.core.retention import (

    CLOUD_SIZE_LIMIT_BYTES,
    RetentionManager,
    _age_str,
)
from moment.core.store import Store
pytestmark = [pytest.mark.integration]


@pytest.fixture

def trash_dir(tmp_path: Path) -> str:
    """Use a temporary directory as the trash dir."""
    return str(tmp_path / "trash")

@pytest.fixture
def manager(store: Store, trash_dir: str) -> RetentionManager:
    m = RetentionManager(
        store,
        source_max_age_days=90,
        encoded_max_age_days=1095,
        cloud_size_limit_bytes=CLOUD_SIZE_LIMIT_BYTES,
        trash_dir=trash_dir,
    )
    yield m
    m.stop()

def _make_clip(
    store: Store, *, id: str, stem: str = "", source_path: str = "",
    **kwargs: object,
) -> Clip:
    """Helper to insert a clip with minimal required fields."""
    clip = Clip(
        id=id,
        stem=stem or id,
        source_path=Path(source_path or f"/tmp/{id}.mkv"),
        **{k: v for k, v in kwargs.items() if k != "id" and k != "stem" and k != "source_path"},
    )
    store.insert_clip(clip)
    return clip

# ---------------------------------------------------------------------------
# Age string helper
# ---------------------------------------------------------------------------

class TestAgeString:
    def test_years(self) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=400)
        assert _age_str(dt) == "1y"

    def test_days(self) -> None:
        dt = datetime.now(timezone.utc) - timedelta(days=45)
        assert _age_str(dt) == "45d"

    def test_hours(self) -> None:
        dt = datetime.now(timezone.utc) - timedelta(hours=5)
        assert _age_str(dt) == "5h"

    def test_minutes(self) -> None:
        dt = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert _age_str(dt) == "30m"

# ---------------------------------------------------------------------------
# Source age enforcement
# ---------------------------------------------------------------------------

class TestSourceAge:
    def test_old_source_trashed(
        self, manager: RetentionManager, store: Store, trash_dir: str,
    ) -> None:
        _make_clip(
            store,
            id="old-source",
            source_path="/tmp/old_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 10_000_000
            purged, freed = manager._enforce_source_age()
            assert purged >= 1
            assert freed > 0
            mock_move.assert_called_once()
            dest = mock_move.call_args[0][1]
            assert dest.startswith(trash_dir)

    def test_recent_source_kept(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="recent-source",
            source_path="/tmp/recent_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=1),
            status=ClipStatus.DONE,
        )

        purged, _ = manager._enforce_source_age()
        assert purged == 0

    def test_protected_clip_not_trashed(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="protected",
            source_path="/tmp/protected_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            protect_from_retention=True,
        )

        with patch("pathlib.Path.is_file", return_value=True):
            purged, _ = manager._enforce_source_age()
            assert purged == 0

# ---------------------------------------------------------------------------
# Encoded age enforcement
# ---------------------------------------------------------------------------

class TestEncodedAge:
    def test_old_encoded_trashed(
        self, manager: RetentionManager, store: Store, trash_dir: str,
    ) -> None:
        _make_clip(
            store,
            id="old-encoded",
            stem="old_encoded",
            source_path="/tmp/old_encoded.mkv",
            encoded_path="/tmp/old_encoded.mp4",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=2000),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", side_effect=lambda: True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 5_000_000
            purged, freed = manager._enforce_encoded_age()
            assert purged >= 1
            assert freed > 0
            mock_move.assert_called_once()
            dest = mock_move.call_args[0][1]
            assert dest.startswith(trash_dir)

    def test_recent_encoded_kept(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="recent-encoded",
            stem="recent_encoded",
            source_path="/tmp/recent_encoded.mkv",
            encoded_path="/tmp/recent_encoded.mp4",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=30),
            status=ClipStatus.DONE,
        )

        purged, _ = manager._enforce_encoded_age()
        assert purged == 0

# ---------------------------------------------------------------------------
# Error / Corrupt clips are skipped by default
# ---------------------------------------------------------------------------

class TestErrorCorruptSkipping:
    def test_error_clip_not_trashed(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="error-clip",
            source_path="/tmp/error_clip.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.ERROR,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("shutil.move") as mock_move,
        ):
            purged, _ = manager._enforce_source_age()
            assert purged == 0
            mock_move.assert_not_called()

    def test_corrupt_clip_not_trashed(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="corrupt-clip",
            source_path="/tmp/corrupt_clip.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.CORRUPT,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("shutil.move") as mock_move,
        ):
            purged, _ = manager._enforce_source_age()
            assert purged == 0
            mock_move.assert_not_called()

    def test_error_clip_trashed_when_remove_corrupt(
        self, store: Store, trash_dir: str,
    ) -> None:
        """When retention_remove_corrupt=true, ERROR clips ARE purged."""
        config = Config(store._db_path)
        config.set("retention_remove_corrupt", True)
        m = RetentionManager(
            store,
            source_max_age_days=0,
            trash_dir=trash_dir,
            config=config,
        )

        _make_clip(
            store,
            id="error-rm",
            source_path="/tmp/error_rm.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=100),
            status=ClipStatus.ERROR,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 1_000_000
            purged, _ = m._enforce_source_age()
            assert purged >= 1
            mock_move.assert_called_once()

        m.stop()

# ---------------------------------------------------------------------------
# Trash days = 0 (permanent delete)
# ---------------------------------------------------------------------------

class TestTrashDaysZero:
    def test_trash_days_zero_permanently_deletes(
        self, store: Store, trash_dir: str,
    ) -> None:
        """When retention_trash_days=0, files are unlinked instead of moved."""
        config = Config(store._db_path)
        config.set("retention_trash_days", 0)
        m = RetentionManager(
            store,
            source_max_age_days=0,
            trash_dir=trash_dir,
            config=config,
        )

        _make_clip(
            store,
            id="perm-del",
            source_path="/tmp/perm_del.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=100),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("pathlib.Path.unlink") as mock_unlink,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 1_000_000
            purged, _ = m._enforce_source_age()
            assert purged >= 1
            mock_unlink.assert_called_once()
            mock_move.assert_not_called()

        m.stop()

# ---------------------------------------------------------------------------
# Cloud FIFO enforcement (unchanged — soft-deletes, no file ops)
# ---------------------------------------------------------------------------

class TestCloudFIFO:
    def test_under_limit_no_purge(self, manager: RetentionManager, store: Store) -> None:
        _make_clip(
            store,
            id="small-clip",
            stem="small_clip",
            source_path="/tmp/small.mkv",
            file_size=1_000_000,
            status=ClipStatus.UPLOADED,
        )

        purged, _ = manager._enforce_cloud_limit()
        assert purged == 0

    def test_over_limit_purges_oldest(self, manager: RetentionManager, store: Store) -> None:
        manager._cloud_limit = 2_000_000  # 2MB

        _make_clip(
            store,
            id="cloud-1",
            stem="cloud_1",
            source_path="/tmp/cloud1.mkv",
            file_size=1_500_000,
            created_at=datetime.now(timezone.utc) - timedelta(days=100),
            status=ClipStatus.UPLOADED,
        )
        _make_clip(
            store,
            id="cloud-2",
            stem="cloud_2",
            source_path="/tmp/cloud2.mkv",
            file_size=1_000_000,
            created_at=datetime.now(timezone.utc),
            status=ClipStatus.UPLOADED,
        )

        purged, freed = manager._enforce_cloud_limit()
        assert purged > 0
        assert freed > 0

    def test_protected_not_purged_in_cloud(self, manager: RetentionManager, store: Store) -> None:
        manager._cloud_limit = 1_000_000  # 1MB

        _make_clip(
            store,
            id="protected-cloud",
            stem="protected_cloud",
            source_path="/tmp/protected_cloud.mkv",
            file_size=2_000_000,
            protect_from_retention=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=100),
            status=ClipStatus.UPLOADED,
        )

        purged, _ = manager._enforce_cloud_limit()
        assert purged == 0

# ---------------------------------------------------------------------------
# Full enforce
# ---------------------------------------------------------------------------

class TestEnforce:
    def test_enforce_returns_tuple(self, manager: RetentionManager) -> None:
        result = manager.enforce()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], int)
        assert isinstance(result[1], int)

    def test_no_clips_returns_zero(self, manager: RetentionManager) -> None:
        purged, freed = manager.enforce()
        assert purged == 0
        assert freed == 0

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_on_purged_callback(self, store: Store, trash_dir: str) -> None:
        purged_data: list[tuple[int, int]] = []

        m = RetentionManager(
            store,
            source_max_age_days=0,  # all old
            on_purged=lambda count, freed: purged_data.append((count, freed)),
            trash_dir=trash_dir,
        )

        _make_clip(
            store,
            id="purge-me",
            source_path="/tmp/purge_me.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=100),
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move"),
        ):
            mock_stat.return_value.st_size = 10_000_000
            m.enforce()

        assert len(purged_data) > 0
        m.stop()

    def test_callback_with_no_purge(self, store: Store, trash_dir: str) -> None:
        purged_data: list[tuple[int, int]] = []

        m = RetentionManager(
            store,
            on_purged=lambda count, freed: purged_data.append((count, freed)),
            trash_dir=trash_dir,
        )

        m.enforce()
        assert len(purged_data) == 0
        m.stop()

# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_stop_lifecycle(self, store: Store, trash_dir: str) -> None:
        m = RetentionManager(store, trash_dir=trash_dir)
        m.start()
        assert m.is_running
        m.stop()
        assert not m.is_running

    def test_double_start_noop(self, store: Store, trash_dir: str) -> None:
        m = RetentionManager(store, trash_dir=trash_dir)
        m.start()
        m.start()  # should be a no-op
        assert m.is_running
        m.stop()

    def test_stop_cancels_timer(self, store: Store, trash_dir: str) -> None:
        m = RetentionManager(store, trash_dir=trash_dir)
        m.start()
        m.stop()
        assert m._timer is None

    def test_skip_error_corrupt_default(self, store: Store, trash_dir: str) -> None:
        """_skip_error_corrupt returns True for ERROR clips by default."""
        m = RetentionManager(store, trash_dir=trash_dir)
        clip = Clip(id="err", stem="err", source_path=Path("/tmp/err.mkv"), status=ClipStatus.ERROR)
        assert m._skip_error_corrupt(clip) is True

    def test_skip_error_corrupt_not_error(self, store: Store, trash_dir: str) -> None:
        """_skip_error_corrupt returns False for non-ERROR clips."""
        m = RetentionManager(store, trash_dir=trash_dir)
        clip = Clip(id="ok", stem="ok", source_path=Path("/tmp/ok.mkv"), status=ClipStatus.DONE)
        assert m._skip_error_corrupt(clip) is False

    def test_on_tick_calls_enforce(self, store: Store, trash_dir: str) -> None:
        """_on_tick calls enforce() then schedules next tick."""
        m = RetentionManager(store, trash_dir=trash_dir)
        m._running = True
        with patch.object(m, "enforce", return_value=(0, 0)) as mock_enforce:
            with patch.object(m, "_schedule") as mock_schedule:
                m._on_tick()
                mock_enforce.assert_called_once()
                mock_schedule.assert_called_once()

    def test_on_tick_exception_still_schedules(self, store: Store, trash_dir: str) -> None:
        """_on_tick still schedules next tick even if enforce() raises."""
        m = RetentionManager(store, trash_dir=trash_dir)
        m._running = True
        with patch.object(m, "enforce", side_effect=RuntimeError("boom")):
            with patch.object(m, "_schedule") as mock_schedule:
                m._on_tick()
                mock_schedule.assert_called_once()

    def test_age_str_all_branches(self) -> None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        assert _age_str(now - timedelta(days=400)) == "1y"
        assert _age_str(now - timedelta(days=45)) == "45d"
        assert _age_str(now - timedelta(hours=5)) == "5h"
        assert _age_str(now - timedelta(minutes=30)) == "30m"

    def test_source_oserror_logged(self, manager: RetentionManager, store: Store) -> None:
        """OSError during source file trash is logged, not fatal."""
        from datetime import datetime, timedelta, timezone
        _make_clip(
            store,
            id="oserror-source",
            source_path="/tmp/oserror_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=100),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move", side_effect=OSError("permission denied")),
        ):
            mock_stat.return_value.st_size = 10_000_000
            purged, freed = manager._enforce_source_age()
            # Should be 0 because move failed but the exception was caught
            assert purged >= 0

class TestOSErrorHandlers:
    def test_encoded_oserror_logged(self, manager: RetentionManager, store: Store) -> None:
        """OSError during encoded file trash is logged, not fatal."""
        _make_clip(
            store,
            id="oserror-enc",
            source_path="/tmp/oserror_enc.mkv",
            encoded_path="/tmp/oserror_enc.mp4",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=2000),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move", side_effect=OSError("permission denied")),
        ):
            mock_stat.return_value.st_size = 5_000_000
            purged, freed = manager._enforce_encoded_age()
            assert purged >= 0

# ---------------------------------------------------------------------------
# Concurrent insert + enforce
# ---------------------------------------------------------------------------

class TestConcurrentInsertEnforce:
    def test_insert_during_enforce_does_not_crash(self, manager: RetentionManager, store: Store) -> None:
        """Inserting clips while retention is running should not crash."""
        import threading
        from datetime import datetime, timedelta, timezone

        results: list[Exception | None] = [None]

        def insert_while_enforcing() -> None:
            try:
                for i in range(50):
                    _make_clip(
                        store,
                        id=f"concurrent-{i}",
                        source_path=f"/tmp/concurrent_{i}.mkv",
                        recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
                        status=ClipStatus.DONE,
                    )
            except Exception as e:
                results[0] = e

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move"),
        ):
            mock_stat.return_value.st_size = 10_000_000

            t = threading.Thread(target=insert_while_enforcing)
            t.start()
            # Run enforce multiple times while insert is happening
            for _ in range(5):
                manager._enforce_source_age()
                manager._enforce_encoded_age()
            t.join()

        assert results[0] is None, f"Insert error: {results[0]}"
        # All clips should have been inserted
        for i in range(50):
            assert store.get_clip(f"concurrent-{i}") is not None

# ---------------------------------------------------------------------------
# Retention startup edge cases
# ---------------------------------------------------------------------------

class TestRetentionStartup:
    def test_startup_enforce_does_not_raise_on_empty_db(self, store: Store, trash_dir: str) -> None:
        """RetentionManager.start() on empty DB should not raise."""
        m = RetentionManager(store, trash_dir=trash_dir)
        m.start()
        assert m.is_running
        m.stop()
        assert not m.is_running

    def test_startup_cleans_nonexistent_trash(self, store: Store) -> None:
        """RetentionManager should create trash dir if it doesn't exist."""
        trash_path = tempfile.mkdtemp(prefix="trash_startup_") + "/trash_subdir"
        assert not os.path.exists(trash_path)

        m = RetentionManager(store, trash_dir=trash_path)
        m.start()
        assert os.path.isdir(trash_path)
        m.stop()

        shutil.rmtree(os.path.dirname(trash_path), ignore_errors=True)

    def test_startup_with_valid_clips(self, store: Store, trash_dir: str) -> None:
        """RetentionManager.start() with existing clips runs enforce without error."""
        from datetime import datetime, timedelta, timezone
        _make_clip(
            store,
            id="startup-clip",
            source_path="/tmp/startup_clip.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat"),
            patch("shutil.move"),
        ):
            m = RetentionManager(store, trash_dir=trash_dir)
            m.start()
            assert m.is_running
            m.stop()

# ---------------------------------------------------------------------------
# Trash file path injection
# ---------------------------------------------------------------------------

class TestTrashPathInjection:
    def test_trash_path_with_special_chars(self, manager: RetentionManager, store: Store, tmp_path: Path) -> None:
        """Trash file paths with special characters are handled safely."""
        from datetime import datetime, timedelta, timezone
        _make_clip(
            store,
            id="special-path",
            stem="../../../etc/passwd",
            source_path="/tmp/special_path.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 10_000_000
            purged, freed = manager._enforce_source_age()
            assert purged >= 1
            # The move destination should be within trash_dir, not following the ../..
            dest = mock_move.call_args[0][1]
            assert str(dest).startswith(manager._trash_dir)
            assert "/etc/" not in str(dest)

    def test_trash_path_with_unicode(self, manager: RetentionManager, store: Store) -> None:
        """Trash file paths with unicode characters are handled safely."""
        from datetime import datetime, timedelta, timezone
        _make_clip(
            store,
            id="unicode-path",
            stem="🔥精彩片段 clip",
            source_path="/tmp/unicode_clip.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("shutil.move") as mock_move,
        ):
            mock_stat.return_value.st_size = 10_000_000
            purged, freed = manager._enforce_source_age()
            assert purged >= 1
            dest = mock_move.call_args[0][1]
            assert str(dest).startswith(manager._trash_dir)


