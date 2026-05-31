"""Tests for core/updater.py — version checking and PyPI update detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from moment.core.updater import (
    _is_newer,
    _parse_version,
    check_for_updates,
)


class TestParseVersion:
    def test_simple_major_minor_patch(self) -> None:
        assert _parse_version("0.1.1") == (0, 1, 1)

    def test_calver(self) -> None:
        assert _parse_version("2024.12.0") == (2024, 12, 0)

    def test_pre_release_suffix(self) -> None:
        assert _parse_version("1.0.0a1") == (1, 0, 0)

    def test_pre_release_suffix_longer(self) -> None:
        assert _parse_version("2.1.0-beta.3") == (2, 1, 0)

    def test_empty(self) -> None:
        assert _parse_version("") == (0,)

    def test_invalid(self) -> None:
        assert _parse_version("abc.def") == (0,)

    def test_mixed(self) -> None:
        assert _parse_version("1.2.3.4") == (1, 2, 3, 4)

    def test_none(self) -> None:
        """parse_version should safely handle None."""
        assert _parse_version(None) == (0,)  # type: ignore[arg-type]

    def test_partial_numeric(self) -> None:
        assert _parse_version("1.2.3rc1") == (1, 2, 3)


class TestIsNewer:
    def test_strictly_newer(self) -> None:
        assert _is_newer("1.0.0", "0.9.0") is True

    def test_not_newer(self) -> None:
        assert _is_newer("0.9.0", "1.0.0") is False

    def test_equal(self) -> None:
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_calver_newer(self) -> None:
        assert _is_newer("2025.01.0", "2024.12.0") is True


class TestCheckForUpdates:
    def test_returns_result_on_success(self) -> None:
        """Happy path: newer version available."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop") as mock_loop,
                patch("moment.core.updater._is_newer", return_value=True),
            ):
                mock_loop.return_value = AsyncMock()
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=("2.0.0", "1.0.0")
                )

                result = await check_for_updates("1.0.0")
                assert result["available"] is True
                assert result["latest_version"] == "2.0.0"
                assert result["current_version"] == "1.0.0"

        asyncio.run(run())

    def test_no_update_available(self) -> None:
        """When versions are equal, available=False."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop") as mock_loop,
                patch("moment.core.updater._is_newer", return_value=False),
            ):
                mock_loop.return_value = AsyncMock()
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=("1.0.0", "1.0.0")
                )

                result = await check_for_updates("1.0.0")
                assert result["available"] is False

        asyncio.run(run())

    def test_network_failure_returns_no_update(self) -> None:
        """On network error, returns current version as latest."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop") as mock_loop,
            ):
                mock_loop.return_value = AsyncMock()
                mock_loop.return_value.run_in_executor = AsyncMock(return_value=None)

                result = await check_for_updates("1.0.0")
                assert result["available"] is False
                assert result["latest_version"] == "1.0.0"

        asyncio.run(run())

    def test_exception_in_check_handled_gracefully(self) -> None:
        """Any exception during check returns current version as latest."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
            ):
                result = await check_for_updates("1.0.0")
                assert result["available"] is False
                assert result["latest_version"] == "1.0.0"

        asyncio.run(run())

    def test_same_version_no_update(self) -> None:
        """When latest == current, available=False even if is_newer is false."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop") as mock_loop,
            ):
                mock_loop.return_value = AsyncMock()
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=("1.0.0", "1.0.0")
                )

                result = await check_for_updates("1.0.0")
                assert result["available"] is False

        asyncio.run(run())

    def test_fetch_returns_none_on_exception(self) -> None:
        """When _fetch_and_parse raises, returns None gracefully."""
        async def run() -> None:
            with (
                patch("asyncio.get_running_loop") as mock_loop,
            ):
                mock_loop.return_value = AsyncMock()
                # When fetch returns None (parsed is None)
                mock_loop.return_value.run_in_executor = AsyncMock(return_value=None)

                result = await check_for_updates("1.0.0")
                assert result["available"] is False
                assert result["latest_version"] == "1.0.0"

        asyncio.run(run())
