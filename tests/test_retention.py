"""Tests for core/retention.py — age-based and disk-space retention policies."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from clip_tray.core.models import Clip, ClipStatus
from clip_tray.core.retention import (
    CLOUD_SIZE_LIMIT_BYTES,
    ENCODED_MAX_AGE_DAYS,
    SOURCE_MAX_AGE_DAYS,
    RetentionManager,
    _age_str,
)
from clip_tray.core.store import Store


@pytest.fixture
def manager(store: Store) -> RetentionManager:
    m = RetentionManager(
        store,
        source_max_age_days=90,
        encoded_max_age_days=1095,
        cloud_size_limit_bytes=CLOUD_SIZE_LIMIT_BYTES,
    )
    yield m
    m.stop()


def _make_clip(store: Store, *, id: str, stem: str = "", source_path: str = "", **kwargs: object) -> Clip:
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
    def test_old_source_deleted(self, manager: RetentionManager, store: Store) -> None:
        clip = _make_clip(
            store,
            id="old-source",
            source_path="/tmp/old_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ClipStatus.DONE,
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.unlink"),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 10_000_000
            purged, freed = manager._enforce_source_age()
            assert purged >= 1
            assert freed > 0

    def test_recent_source_kept(self, manager: RetentionManager, store: Store) -> None:
        clip = _make_clip(
            store,
            id="recent-source",
            source_path="/tmp/recent_source.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=1),
            status=ClipStatus.DONE,
        )

        purged, _ = manager._enforce_source_age()
        assert purged == 0

    def test_protected_clip_not_deleted(self, manager: RetentionManager, store: Store) -> None:
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
    def test_old_encoded_deleted(self, manager: RetentionManager, store: Store) -> None:
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
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.unlink"),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 5_000_000
            purged, freed = manager._enforce_encoded_age()
            assert purged >= 1
            assert freed > 0

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
# Cloud FIFO enforcement
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
        # Use a small limit for testing
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
    def test_on_purged_callback(self, store: Store) -> None:
        purged_data: list[tuple[int, int]] = []

        m = RetentionManager(
            store,
            source_max_age_days=0,  # all old
            on_purged=lambda count, freed: purged_data.append((count, freed)),
        )

        _make_clip(
            store,
            id="purge-me",
            source_path="/tmp/purge_me.mkv",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=100),
        )

        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.unlink"),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 10_000_000
            m.enforce()

        assert len(purged_data) > 0
        m.stop()

    def test_callback_with_no_purge(self, store: Store) -> None:
        purged_data: list[tuple[int, int]] = []

        m = RetentionManager(
            store,
            on_purged=lambda count, freed: purged_data.append((count, freed)),
        )

        m.enforce()
        assert len(purged_data) == 0
        m.stop()


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_stop_lifecycle(self, store: Store) -> None:
        m = RetentionManager(store)
        m.start()
        assert m.is_running
        m.stop()
        assert not m.is_running
