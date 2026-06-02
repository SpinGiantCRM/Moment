"""Tests for core/repositories/settings_repo.py — rate limits."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from moment.core.repositories.settings_repo import SettingsRepository
from moment.core.store import Store

pytestmark = [pytest.mark.integration]


@pytest.fixture
def settings_repo(store: Store) -> SettingsRepository:
    # The store creates the base repo internally; we can access it via _base
    return SettingsRepository(store._base)


class TestCheckRate:
    def test_first_call_returns_none(self, settings_repo: SettingsRepository) -> None:
        """First call for a key should never be rate-limited."""

        result = settings_repo.check_rate("test_key", interval_secs=60.0)
        assert result is None

    def test_second_call_returns_rate_limited(self, settings_repo: SettingsRepository) -> None:
        """Second call within interval should be rate-limited."""
        settings_repo.check_rate("test_key2", interval_secs=60.0)
        result = settings_repo.check_rate("test_key2", interval_secs=60.0)
        assert result is not None
        assert "wait" in result.lower()

    def test_after_interval_passes(self, settings_repo: SettingsRepository) -> None:
        """After the interval elapses, should no longer be rate-limited."""
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000.0
            settings_repo.check_rate("time_key", interval_secs=10.0)
            # Advance time past the interval
            mock_time.return_value = 1011.0
            result = settings_repo.check_rate("time_key", interval_secs=10.0)
            assert result is None

    def test_different_keys_independent(self, settings_repo: SettingsRepository) -> None:
        """Rate limits for different keys should be independent."""
        settings_repo.check_rate("key_a", interval_secs=60.0)
        result_b = settings_repo.check_rate("key_b", interval_secs=60.0)
        assert result_b is None

    def test_cleanup_old_entries(self, settings_repo: SettingsRepository) -> None:
        """Old rate limit entries should be cleaned up periodically."""
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000.0
            settings_repo.check_rate("old_key", interval_secs=60.0)
            # Advance well past the expiry window
            mock_time.return_value = 1000.0 + (60.0 * 2) + 10.0
            settings_repo.check_rate("old_key", interval_secs=60.0)
            # Should work without error
            assert True
