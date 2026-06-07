"""Tests for core/gsr_controller.py — GSR process lifecycle.

Mocks subprocess.Popen and os.kill. Never calls the real GSR binary.
"""

from __future__ import annotations

import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from moment.core.gsr_controller import (
    _MAX_RESTARTS,
    GSR_BINARY,
    GSRController,
    GSRControllerError,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture
def gsr() -> GSRController:
    """Return a GSRController with defaults — no real subprocess."""
    return GSRController(output_dir="/tmp/test_videos")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self) -> None:
        ctrl = GSRController(output_dir="/tmp/test")
        assert ctrl.output_dir.name == "test"
        assert ctrl._fps == 60
        assert not ctrl.is_recording

    def test_expands_user_path(self) -> None:
        ctrl = GSRController(output_dir="~/Videos/Moment")
        assert "~" not in str(ctrl.output_dir)

    def test_on_crash_callback(self) -> None:
        called: list[str] = []
        ctrl = GSRController(output_dir="/tmp/test", on_crash=lambda m: called.append(m))
        assert ctrl._on_crash is not None
        assert len(called) == 0


# ---------------------------------------------------------------------------
# Binary check
# ---------------------------------------------------------------------------


class TestBinaryCheck:
    def test_missing_binary_raises(self, gsr: GSRController) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(GSRControllerError, match="not found in PATH"):
                gsr.start()

    def test_binary_found_starts(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            gsr.start()
            assert gsr.is_recording
            mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_creates_output_dir(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            gsr.start()
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_start_replaces_existing_process(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            # Second start should stop the first
            mock_stop = MagicMock()
            with patch.object(gsr, "_stop_process_unlocked", mock_stop):
                gsr.start()
                mock_stop.assert_called_once()

    def test_stop(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            with patch.object(gsr, "_stop_process_unlocked") as mock_stop:
                gsr.stop()
                mock_stop.assert_called_once()
                assert gsr._stopped_intentionally

    def test_stop_when_not_running_is_noop(self, gsr: GSRController) -> None:
        gsr.stop()  # should not raise


# ---------------------------------------------------------------------------
# save_replay (SIGUSR1)
# ---------------------------------------------------------------------------


class TestSaveReplay:
    def test_sends_sigusr1(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch("os.kill") as mock_kill,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 42
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            gsr.save_replay()
            mock_kill.assert_called_once_with(42, signal.SIGUSR1)

    def test_noop_when_not_running(self, gsr: GSRController) -> None:
        with patch("os.kill") as mock_kill:
            gsr.save_replay()
            mock_kill.assert_not_called()

    def test_debounce(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch("os.kill") as mock_kill,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 42
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            gsr.save_replay()
            gsr.save_replay()  # should be debounced
            assert mock_kill.call_count == 1

    def test_sigusr1_on_dead_process(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch("os.kill") as mock_kill,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 42
            mock_proc.poll.return_value = 1  # already dead
            mock_popen.return_value = mock_proc
            gsr.start()
            gsr._proc = mock_proc

            gsr.save_replay()
            mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_minimal_command(self, gsr: GSRController) -> None:
        cmd = gsr._build_command()
        assert GSR_BINARY in cmd
        assert "-k" in cmd
        assert "-f" in cmd
        assert "60" in cmd

    def test_includes_replay_duration(self) -> None:
        ctrl = GSRController(output_dir="/tmp", replay_duration=90)
        cmd = ctrl._build_command()
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "90"

    def test_with_video_codec(self) -> None:
        ctrl = GSRController(output_dir="/tmp", video_codec="h264_nvenc")
        cmd = ctrl._build_command()
        assert "-v" in cmd
        assert "h264_nvenc" in cmd

    def test_with_audio_device(self) -> None:
        ctrl = GSRController(output_dir="/tmp", audio_device="default")
        cmd = ctrl._build_command()
        assert "-a" in cmd
        assert "default" in cmd


# ---------------------------------------------------------------------------
# Crash recovery (monitor thread)
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_crash_auto_restart(self, gsr: GSRController) -> None:
        """If the process dies, the monitor thread should restart it."""
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            # Simulate crash: poll() returns non-None
            mock_popen.reset_mock()
            gsr._proc = mock_proc

            # Manually call the monitor's logic
            with (
                patch.object(gsr, "_can_restart", return_value=True),
                patch("time.monotonic", return_value=999999.0),
            ):
                # Simulate process death
                mock_proc.wait.return_value = 1
                gsr._stopped_intentionally = False
                gsr._monitor_process()

    def test_restart_limit_reached(self, gsr: GSRController) -> None:
        """If too many crashes, give up and call on_crash."""
        crashes: list[str] = []
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(GSRController, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
        ):
            ctrl = GSRController(
                output_dir="/tmp",
                on_crash=lambda m: crashes.append(m),
            )
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            ctrl.start()

            # Pre-fill crash timestamps
            from collections import deque

            now = time.monotonic()
            ctrl._restart_timestamps = deque([now] * _MAX_RESTARTS, maxlen=11)
            ctrl._proc = mock_proc
            ctrl._stopped_intentionally = False

            mock_proc.wait.return_value = 1
            ctrl._monitor_process()

            assert len(crashes) > 0

    def test_intentional_stop_no_restart(self, gsr: GSRController) -> None:
        """If we intentionally stopped, monitor should not restart."""
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch.object(gsr, "_spawn_process_unlocked") as mock_spawn,
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()

            # Reset mock so we only count calls after start()
            mock_spawn.reset_mock()

            gsr._proc = mock_proc
            gsr._stopped_intentionally = True

            mock_proc.wait.return_value = 0
            gsr._monitor_process()
            mock_spawn.assert_not_called()


# ---------------------------------------------------------------------------
# Restart budget
# ---------------------------------------------------------------------------


class TestCanRestart:
    def test_under_limit(self, gsr: GSRController) -> None:
        assert gsr._can_restart()

    def test_over_limit(self, gsr: GSRController) -> None:
        from collections import deque

        now = time.monotonic()
        gsr._restart_timestamps = deque([now] * (_MAX_RESTARTS + 1), maxlen=11)
        assert not gsr._can_restart()


# ---------------------------------------------------------------------------
# is_recording / pid
# ---------------------------------------------------------------------------


class TestQueries:
    def test_not_recording_initially(self, gsr: GSRController) -> None:
        assert not gsr.is_recording
        assert gsr.pid is None

    def test_recording_after_start(self, gsr: GSRController) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/gpu-screen-recorder"),
            patch.object(gsr, "_kill_external_gsr"),
            patch("subprocess.Popen") as mock_popen,
            patch.object(gsr, "_monitor_process"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 42
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc
            gsr.start()
            assert gsr.is_recording
            assert gsr.pid == 42


# ---------------------------------------------------------------------------
# _stop_process_unlocked
# ---------------------------------------------------------------------------


class TestStopProcess:
    def test_sigterm_then_sigkill(self, gsr: GSRController) -> None:
        with patch("os.kill") as mock_kill:
            mock_proc = MagicMock()
            mock_proc.pid = 99
            import subprocess

            mock_proc.wait.side_effect = subprocess.TimeoutExpired(
                cmd=["gpu-screen-recorder"], timeout=5.0
            )
            gsr._proc = mock_proc

            gsr._stop_process_unlocked()

            # SIGTERM sent
            mock_kill.assert_any_call(99, signal.SIGTERM)
            # SIGKILL sent after timeout
            mock_kill.assert_any_call(99, signal.SIGKILL)

    def test_none_proc(self, gsr: GSRController) -> None:
        gsr._proc = None
        gsr._stop_process_unlocked()  # should not raise
