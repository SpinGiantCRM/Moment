"""Tests for core/game_monitor.py — game process detection via /proc and nvidia-smi."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from moment.core.game_monitor import SCAN_INTERVAL, GameMonitor


@pytest.fixture
def monitor() -> GameMonitor:
    m = GameMonitor(
        game_binaries={"test_game", "cs2"},
        use_nvidia_check=False,
    )
    yield m
    m.stop()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_default_state_is_idle(self, monitor: GameMonitor) -> None:
        assert monitor.state == "IDLE"
        assert monitor.active_game is None

    def test_not_running_initially(self) -> None:
        m = GameMonitor()
        assert not m.is_running

    def test_default_scan_interval(self) -> None:
        m = GameMonitor()
        assert m._interval == SCAN_INTERVAL

    def test_custom_binaries(self) -> None:
        m = GameMonitor(game_binaries={"my_game"})
        assert "my_game" in m.game_binaries
        assert "cs2" not in m.game_binaries


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_idle_to_active(self, monitor: GameMonitor) -> None:
        with patch.object(monitor, "_find_game_process", return_value="cs2"):
            monitor._scan()
            assert monitor.state == "GAME_ACTIVE"
            assert monitor.active_game == "cs2"

    def test_active_stays_active(self, monitor: GameMonitor) -> None:
        # Manually set to active
        with monitor._lock:
            monitor._state = "GAME_ACTIVE"
            monitor._active_game = "cs2"

        with patch.object(monitor, "_find_game_process", return_value="cs2"):
            monitor._scan()
            assert monitor.state == "GAME_ACTIVE"
            assert monitor.active_game == "cs2"

    def test_active_to_exiting(self, monitor: GameMonitor) -> None:
        with monitor._lock:
            monitor._state = "GAME_ACTIVE"
            monitor._active_game = "cs2"

        with patch.object(monitor, "_find_game_process", return_value=None):
            monitor._scan()
            assert monitor.state == "GAME_EXITING"

    def test_exiting_to_idle(self, monitor: GameMonitor) -> None:
        with monitor._lock:
            monitor._state = "GAME_EXITING"
            monitor._active_game = "cs2"

        with patch.object(monitor, "_find_game_process", return_value=None):
            monitor._scan()
            assert monitor.state == "IDLE"
            assert monitor.active_game is None

    def test_game_switch(self, monitor: GameMonitor) -> None:
        with monitor._lock:
            monitor._state = "GAME_ACTIVE"
            monitor._active_game = "cs2"

        with patch.object(monitor, "_find_game_process", return_value="test_game"):
            monitor._scan()
            assert monitor.active_game == "test_game"

    def test_game_resumed_from_exiting(self, monitor: GameMonitor) -> None:
        with monitor._lock:
            monitor._state = "GAME_EXITING"
            monitor._active_game = "cs2"

        with patch.object(monitor, "_find_game_process", return_value="cs2"):
            monitor._scan()
            assert monitor.state == "GAME_ACTIVE"


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_state_change_callback(self) -> None:
        states: list[tuple[str, str | None]] = []

        m = GameMonitor(
            game_binaries={"cs2"},
            use_nvidia_check=False,
            on_state_changed=lambda s, g: states.append((s, g)),
        )

        with patch.object(m, "_find_game_process", return_value="cs2"):
            m._scan()
            assert ("GAME_ACTIVE", "cs2") in states
        m.stop()

    def test_game_exiting_callback(self) -> None:
        states: list[tuple[str, str | None]] = []

        m = GameMonitor(
            game_binaries={"cs2"},
            use_nvidia_check=False,
            on_state_changed=lambda s, g: states.append((s, g)),
        )

        with m._lock:
            m._state = "GAME_ACTIVE"
            m._active_game = "cs2"

        with patch.object(m, "_find_game_process", return_value=None):
            m._scan()
            assert ("GAME_EXITING", "cs2") in states
        m.stop()

    def test_callback_exception_is_handled(self) -> None:
        def bad_callback(state: str, game: str | None) -> None:
            raise RuntimeError("callback error")

        m = GameMonitor(
            game_binaries={"cs2"},
            use_nvidia_check=False,
            on_state_changed=bad_callback,
        )

        with patch.object(m, "_find_game_process", return_value="cs2"):
            # Should not raise
            m._scan()
        m.stop()


# ---------------------------------------------------------------------------
# Process scanning
# ---------------------------------------------------------------------------

class TestProcessScanning:
    def test_find_game_in_proc(self, monitor: GameMonitor) -> None:
        """Mock reading /proc to find a game process."""
        mock_dir = ["1", "2", "1234", "5678", "self"]

        def mock_read_comm(path: str) -> str:
            if "1234" in path:
                return "cs2"
            if "5678" in path:
                return "firefox"
            raise FileNotFoundError

        with (
            patch("os.listdir", return_value=mock_dir),
            patch("builtins.open", create=True) as mock_open,
        ):
            mock_open.side_effect = lambda p, *a, **kw: _MockFile(mock_read_comm(p))
            result = monitor._find_game_process()
            assert result == "cs2"

    def test_no_game_found(self, monitor: GameMonitor) -> None:
        with patch("os.listdir", return_value=["1", "2"]), \
             patch("builtins.open", side_effect=FileNotFoundError):
            result = monitor._find_game_process()
            assert result is None


class _MockFile:
    def __init__(self, content: str) -> None:
        self._content = content

    def __enter__(self) -> _MockFile:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def read(self) -> str:
        return self._content


# ---------------------------------------------------------------------------
# /proc accessibility warning
# ---------------------------------------------------------------------------

class TestProcAccessibility:
    def test_warns_when_proc_restricted(self, monitor: GameMonitor) -> None:
        """When /proc/1/comm is not readable, a WARNING is logged once."""
        with (
            patch("os.access", return_value=False),
            patch("moment.core.game_monitor.logger") as mock_logger,
        ):
            monitor._check_proc_accessible()
            monitor._check_proc_accessible()  # second call should not log again

            warning_calls = [
                c for c in mock_logger.warning.call_args_list
                if c[0] and "hidepid" in str(c[0])
            ]
            assert len(warning_calls) == 1
            msg = warning_calls[0][0][0]
            assert "hidepid=2" in msg
            assert "/proc" in msg

    def test_no_warning_when_proc_accessible(self, monitor: GameMonitor) -> None:
        """When /proc is readable, no warning is logged."""
        with (
            patch("os.access", return_value=True),
            patch("moment.core.game_monitor.logger") as mock_logger,
        ):
            monitor._check_proc_accessible()
            monitor._check_proc_accessible()

            warning_calls = [
                c for c in mock_logger.warning.call_args_list
                if c[0] and "hidepid" in str(c[0])
            ]
            assert len(warning_calls) == 0

    def test_scan_calls_proc_check(self, monitor: GameMonitor) -> None:
        """_scan() should call _check_proc_accessible before scanning."""
        with (
            patch.object(monitor, "_check_proc_accessible") as mock_check,
            patch.object(monitor, "_find_game_process", return_value=None),
        ):
            monitor._scan()
            mock_check.assert_called_once()

    def test_proc_warned_flag_prevents_repeat(self, monitor: GameMonitor) -> None:
        """After first check, _proc_warned flag prevents re-checking."""
        monitor._proc_warned = True
        with patch("os.access") as mock_access:
            monitor._check_proc_accessible()
            mock_access.assert_not_called()


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_starts_timer(self) -> None:
        m = GameMonitor(game_binaries={"test"}, scan_interval=999.0)
        m.start()
        assert m.is_running
        m.stop()
        assert not m.is_running

    def test_double_start_does_nothing(self) -> None:
        m = GameMonitor(game_binaries={"test"}, scan_interval=999.0)
        m.start()
        m.start()  # no-op
        assert m.is_running
        m.stop()
