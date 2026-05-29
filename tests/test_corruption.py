"""Tests for core/corruption.py — health checks and corrupt clip detection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.corruption import (
    CHECK_INTERVAL,
    DISK_CRITICAL_GB,
    DISK_WARNING_GB,
    PIPELINE_STUCK_MINUTES,
    TEMP_MAX_AGE,
    CorruptionDetector,
)
from moment.core.models import Clip, ClipStatus
from moment.core.store import Store


@pytest.fixture
def detector(store: Store) -> CorruptionDetector:
    d = CorruptionDetector(store, check_interval=999.0)
    yield d
    d.stop()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_not_running_initially(self, store: Store) -> None:
        d = CorruptionDetector(store)
        assert not d.is_running

    def test_default_interval(self, store: Store) -> None:
        d = CorruptionDetector(store)
        assert d._interval == CHECK_INTERVAL


# ---------------------------------------------------------------------------
# Clip corruption detection
# ---------------------------------------------------------------------------

class TestCheckClip:
    def test_zero_byte_is_corrupt(self, detector: CorruptionDetector) -> None:
        clip = Clip(
            id=str(uuid.uuid4()),
            stem="empty_clip",
            source_path=Path("/tmp/empty.mkv"),
            file_size=0,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 0
            result = detector.check_clip(clip)
            assert result == ClipStatus.CORRUPT

    def test_normal_clip_is_not_corrupt(self, detector: CorruptionDetector) -> None:
        clip = Clip(
            id=str(uuid.uuid4()),
            stem="good_clip",
            source_path=Path("/tmp/good.mkv"),
            file_size=50_000_000,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 50_000_000
            mock_stat.return_value.st_mtime = 0  # old file
            result = detector.check_clip(clip)
            assert result is None

    def test_missing_file_is_corrupt(self, detector: CorruptionDetector) -> None:
        clip = Clip(
            id=str(uuid.uuid4()),
            stem="missing",
            source_path=Path("/tmp/nonexistent.mkv"),
        )

        with patch("pathlib.Path.is_file", return_value=False):
            result = detector.check_clip(clip)
            assert result == ClipStatus.CORRUPT


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_check_returns_list(self, detector: CorruptionDetector) -> None:
        issues = detector.check()
        assert isinstance(issues, list)

    def test_disk_space_warning(self, detector: CorruptionDetector) -> None:
        with patch(
            "moment.core.corruption.disk_usage",
            return_value=(500_000_000_000, 498_000_000_000, 2_000_000_000),  # 2GB free
        ):
            issues = detector.check()
            assert any("WARNING" in i for i in issues)

    def test_disk_space_critical(self, detector: CorruptionDetector) -> None:
        with patch(
            "moment.core.corruption.disk_usage",
            return_value=(500_000_000_000, 499_500_000_000, 500_000_000),  # 0.5GB free
        ):
            issues = detector.check()
            assert any("CRITICAL" in i for i in issues)

    def test_disk_space_ok(self, detector: CorruptionDetector) -> None:
        with patch(
            "moment.core.corruption.disk_usage",
            return_value=(1_000_000_000_000, 500_000_000_000, 500_000_000_000),  # 500GB free
        ):
            issues = detector.check()
            assert not any("disk" in i.lower() for i in issues)

    def test_temp_cleanup(self, detector: CorruptionDetector, tmp_path: Path) -> None:
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        stale_file = temp_dir / "old_temp.mp4"
        stale_file.write_bytes(b"stale data")

        # Make file older than max age
        import os
        import time
        old_time = time.time() - TEMP_MAX_AGE - 60
        os.utime(str(stale_file), (old_time, old_time))

        with patch("moment.core.corruption.get_temp_dir", return_value=str(temp_dir)):
            issues = detector.check()
            # File should be deleted
            assert not stale_file.exists()

    def test_db_integrity_ok(self, detector: CorruptionDetector) -> None:
        with patch.object(detector, "_check_db_integrity", return_value=[]):
            issues = detector.check()
            assert not any("Database integrity check failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_warning_callback(self, store: Store) -> None:
        warnings: list[str] = []

        d = CorruptionDetector(
            store,
            on_warning=lambda msg: warnings.append(msg),
            check_interval=999.0,
        )

        with patch(
            "moment.core.corruption.disk_usage",
            return_value=(500_000_000_000, 498_000_000_000, 2_000_000_000),
        ):
            d.check()
            assert len(warnings) > 0
        d.stop()

    def test_critical_callback(self, store: Store) -> None:
        criticals: list[str] = []

        d = CorruptionDetector(
            store,
            on_critical=lambda msg: criticals.append(msg),
            check_interval=999.0,
        )

        with patch(
            "moment.core.corruption.disk_usage",
            return_value=(500_000_000_000, 499_500_000_000, 500_000_000),
        ):
            d.check()
            assert any("CRITICAL" in c for c in criticals)
        d.stop()


# ---------------------------------------------------------------------------
# Pipeline stuck detection
# ---------------------------------------------------------------------------

class TestPipelineStuck:
    def test_pipeline_stuck_detection(self, detector: CorruptionDetector, store: Store) -> None:
        """If pending tasks don't change for >30 min, issue a warning."""
        import time

        # Mock get_pending_tasks to return a consistent count
        detector._last_task_count = 3
        detector._last_task_time = time.monotonic() - (PIPELINE_STUCK_MINUTES + 1) * 60

        with patch.object(store, "get_pending_tasks", return_value=[MagicMock()] * 3):
            issues = detector.check()
            assert any("stuck" in i for i in issues)


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_stop_lifecycle(self, store: Store) -> None:
        d = CorruptionDetector(store, check_interval=999.0)
        d.start()
        assert d.is_running
        d.stop()
        assert not d.is_running
