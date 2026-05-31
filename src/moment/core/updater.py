"""Auto-update checker — fetches latest version from PyPI JSON API.

Non-blocking async design: fetches in a thread executor so the Qt
event loop is never stalled.  Version comparison uses simple tuple
splitting (no ``packaging`` dependency).

Usage::

    from moment.core.updater import check_for_updates
    result = await check_for_updates("0.1.0")
    if result["available"]:
        print(f"Update available: {result['latest_version']}")
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import TypedDict

logger = logging.getLogger(__name__)

# The PyPI project name (may differ from the Python package name)
PYPI_PROJECT = "moment-clips"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PROJECT}/json"

# Timeout for the HTTP request (seconds)
_REQUEST_TIMEOUT = 10


class UpdateResult(TypedDict):
    """Result from :func:`check_for_updates`."""

    available: bool
    """``True`` if a newer version was found on PyPI."""

    latest_version: str
    """The latest version string from PyPI (or *current_version* on failure)."""

    current_version: str
    """The version string that was passed in."""


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple.

    Handles standard ``major.minor.patch`` and ``calver`` forms.
    Non-numeric segments are stripped after the first non-digit token.

    >>> _parse_version("0.1.1")
    (0, 1, 1)
    >>> _parse_version("2024.12.0")
    (2024, 12, 0)
    >>> _parse_version("1.0.0a1")
    (1, 0, 0)
    """
    try:
        # Take only leading numeric components (ignore pre-release suffixes)
        parts: list[int] = []
        for part in version.split("."):
            digits = ""
            for ch in part.strip():
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if not digits:
                break
            parts.append(int(digits))
        return tuple(parts) if parts else (0,)
    except (ValueError, TypeError):
        return (0,)


def _is_newer(latest: str, current: str) -> bool:
    """Return ``True`` if *latest* is strictly newer than *current*."""
    return _parse_version(latest) > _parse_version(current)


async def check_for_updates(current_version: str) -> UpdateResult:
    """Check PyPI for a newer version of ``moment-clips``.

    Fetches `the PyPI JSON endpoint <https://pypi.org/pypi/moment-clips/json>`_
    in a background thread so callers on the Qt event loop are never blocked.

    Args:
        current_version: The currently installed version (e.g. ``"0.1.1"``).

    Returns:
        An :class:`UpdateResult` dict.  On network / parse failure the
        *available* field is ``False`` and *latest_version* equals
        *current_version*.
    """
    result: UpdateResult = {
        "available": False,
        "latest_version": current_version,
        "current_version": current_version,
    }

    def _fetch_and_parse() -> tuple[str, str] | None:
        """Blocking HTTP request + JSON parse (runs in thread executor)."""
        req = urllib.request.Request(
            PYPI_URL,
            headers={"User-Agent": "moment-clips-updater/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = str(data.get("info", {}).get("version", ""))
            return latest, current_version
        except Exception:
            return None

    try:
        loop = asyncio.get_running_loop()
        parsed = await loop.run_in_executor(None, _fetch_and_parse)

        if parsed is not None:
            latest, current = parsed
            if latest and _is_newer(latest, current):
                result["available"] = True
                result["latest_version"] = latest

            logger.debug(
                "Update check: installed=%s  latest=%s  available=%s",
                current, latest, result["available"],
            )
    except Exception as exc:
        logger.debug("Update check failed (non-fatal): %s", exc)

    return result
