"""Tests for core/hotkey_daemon.py — global hotkey registration."""

from __future__ import annotations

import builtins
import time
from unittest.mock import patch

import pytest

from moment.core.hotkey_daemon import (
    DEBOUNCE_COOLDOWN,
    HotkeyAction,
    HotkeyDaemon,
    _KdeBackend,
    _SigrtminBackend,
    _X11Backend,
)

# ---------------------------------------------------------------------------
# HotkeyAction enum
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.integration]


class TestHotkeyAction:
    def test_actions_defined(self) -> None:
        assert hasattr(HotkeyAction, "SAVE_30S")
        assert hasattr(HotkeyAction, "SAVE_60S")
        assert hasattr(HotkeyAction, "SAVE_5MIN")
        assert hasattr(HotkeyAction, "SCREENSHOT")
        assert hasattr(HotkeyAction, "BOOKMARK")


# ---------------------------------------------------------------------------
# SigrtminBackend
# ---------------------------------------------------------------------------


class TestSigrtminBackend:
    def test_start_stop_noop(self) -> None:
        backend = _SigrtminBackend()
        backend.start()
        backend.stop()
        # Should not raise


# ---------------------------------------------------------------------------
# KdeBackend
# ---------------------------------------------------------------------------


class TestKdeBackend:
    def test_unavailable_when_no_dbus(self) -> None:
        backend = _KdeBackend({})
        # Force dbus import to fail even if the package is installed
        _import = builtins.__import__

        def _block_dbus(name, *args, **kwargs):
            if name == "dbus" or name.startswith("dbus."):
                raise ImportError(f"No module named '{name}'")
            return _import(name, *args, **kwargs)

        with patch("builtins.__import__", _block_dbus):
            with pytest.raises(RuntimeError, match="dbus"):
                backend.start()


# ---------------------------------------------------------------------------
# X11Backend
# ---------------------------------------------------------------------------


class TestX11Backend:
    def test_lifecycle(self) -> None:
        with patch("moment.core.hotkey_daemon.logger"):
            backend = _X11Backend({})
            backend._running = False  # don't actually start event loop
            backend.start()
            assert backend._thread is not None
            backend.stop()


# ---------------------------------------------------------------------------
# HotkeyDaemon
# ---------------------------------------------------------------------------


@pytest.fixture
def daemon() -> HotkeyDaemon:
    return HotkeyDaemon()


class TestHotkeyDaemon:
    def test_not_running_initially(self, daemon: HotkeyDaemon) -> None:
        assert not daemon.is_running
        assert daemon.backend_name is None

    def test_start_uses_sigrtmin_fallback(self, daemon: HotkeyDaemon) -> None:
        """With no KDE or X11 available, falls back to sigrtmin."""

        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            name = daemon.start()
            assert name == "sigrtmin"
            assert daemon.is_running

        daemon.stop()

    def test_stop(self, daemon: HotkeyDaemon) -> None:
        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        daemon.stop()
        assert not daemon.is_running

    def test_custom_bindings(self) -> None:
        custom = {"F1": HotkeyAction.SAVE_30S}
        daemon = HotkeyDaemon(bindings=custom)
        assert daemon._bindings == custom


# ---------------------------------------------------------------------------
# Hotkey trigger + debounce
# ---------------------------------------------------------------------------


class TestHotkeyTrigger:
    def test_trigger_fires_callback(self) -> None:
        triggered: list[HotkeyAction] = []
        daemon = HotkeyDaemon(on_triggered=lambda a: triggered.append(a))

        # Start with sigrtmin fallback
        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        daemon._handle_action(HotkeyAction.SAVE_30S)
        assert HotkeyAction.SAVE_30S in triggered

        daemon.stop()

    def test_debounce_blocks_rapid_presses(self) -> None:
        triggered: list[HotkeyAction] = []
        daemon = HotkeyDaemon(on_triggered=lambda a: triggered.append(a))

        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        # Fire twice rapidly
        daemon._handle_action(HotkeyAction.SAVE_30S)
        daemon._handle_action(HotkeyAction.SAVE_30S)

        # Only one should register
        assert len(triggered) == 1

        daemon.stop()

    def test_debounce_allows_after_cooldown(self) -> None:
        triggered: list[HotkeyAction] = []
        daemon = HotkeyDaemon(on_triggered=lambda a: triggered.append(a))

        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        daemon._handle_action(HotkeyAction.SAVE_30S)

        # Manually advance the debounce timer
        with daemon._trigger_lock:
            daemon._last_trigger[HotkeyAction.SAVE_30S] = time.monotonic() - DEBOUNCE_COOLDOWN - 1

        daemon._handle_action(HotkeyAction.SAVE_30S)

        assert len(triggered) == 2

        daemon.stop()

    def test_different_actions_not_debounced_together(self) -> None:
        triggered: list[HotkeyAction] = []
        daemon = HotkeyDaemon(on_triggered=lambda a: triggered.append(a))

        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        daemon._handle_action(HotkeyAction.SAVE_30S)
        daemon._handle_action(HotkeyAction.SCREENSHOT)

        assert len(triggered) == 2

        daemon.stop()

    def test_callback_exception_is_handled(self) -> None:
        def bad_callback(a: HotkeyAction) -> None:
            raise RuntimeError("boom")

        daemon = HotkeyDaemon(on_triggered=bad_callback)

        with (
            patch(
                "moment.core.hotkey_daemon._KdeBackend",
                side_effect=RuntimeError("no dbus"),
            ),
            patch(
                "moment.core.hotkey_daemon._X11Backend",
                side_effect=RuntimeError("no xlib"),
            ),
        ):
            daemon.start()

        # Should not raise
        daemon._handle_action(HotkeyAction.SAVE_30S)

        daemon.stop()
