"""Tests for core/recorder_controller.py — gpu-screen-recorder subprocess manager."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.models import GameProfile
from moment.core.recorder_controller import (
    DEFAULT_OUTPUT_DIR,
    RecorderController,
    RecorderError,
    replay_signal_for_duration,
)


@pytest.fixture
def controller() -> RecorderController:
    return RecorderController(output_dir="/tmp/test_videos")


@pytest.fixture
def game_profile() -> GameProfile:
    return GameProfile(
        id="gp1",
        game_name="cs2",
        display_name="Counter-Strike 2",
        capture_fps=120,
        replay_duration=45,
        audio_config={"game_device": "output", "mic_device": "input"},
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_default_output_dir(self) -> None:
        ctrl = RecorderController()
        assert ctrl.output_dir.name in ("Videos", "test_videos")

    def test_custom_output_dir_created(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "custom_recordings"
        ctrl = RecorderController(output_dir=str(out_dir))
        assert out_dir.is_dir()
        assert ctrl.output_dir == out_dir

    def test_not_recording_initially(self, controller: RecorderController) -> None:
        assert not controller.is_recording
        assert controller.current_profile is None


# ---------------------------------------------------------------------------
# Start / stop recording
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_recording(
        self, controller: RecorderController, game_profile: GameProfile
    ) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        # Block wait() so the monitor thread doesn't detect a crash
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            controller.start_recording(game_profile)
            # Prevent monitor thread from interfering
            controller._stopped_intentionally = True

        # Verify process was spawned
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs["start_new_session"] is True
        assert call_kwargs["text"] is True
        assert call_kwargs["stdout"] == subprocess.PIPE
        assert call_kwargs["stderr"] == subprocess.PIPE

        assert controller.is_recording
        assert controller.current_profile is game_profile

    def test_start_no_profile_uses_defaults(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            controller.start_recording()
            controller._stopped_intentionally = True

        assert controller.is_recording
        assert controller.current_profile is None

        # Verify command includes default FPS
        cmd = mock_popen.call_args[0][0]
        assert "-f" in cmd
        assert "60" in cmd  # default fps

    def test_start_stops_existing(self, controller: RecorderController) -> None:
        mock_proc1 = MagicMock(spec=subprocess.Popen)
        mock_proc1.pid = 100
        mock_proc1.poll.return_value = None
        mock_proc1.wait.return_value = 0
        mock_proc2 = MagicMock(spec=subprocess.Popen)
        mock_proc2.pid = 200
        mock_proc2.poll.return_value = None

        with patch("subprocess.Popen", side_effect=[mock_proc1, mock_proc2]):
            controller.start_recording()
            controller._stopped_intentionally = True
            assert controller._proc is mock_proc1

            # Start again — should stop first then spawn new
            with patch.object(controller, "_stop_process_unlocked") as mock_stop:
                controller.start_recording()
                mock_stop.assert_called_once()

    def test_stop_recording(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            controller.start_recording()
            controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.stop_recording()
            mock_kill.assert_called_once_with(100, signal.SIGTERM)

        assert not controller.is_recording
        assert controller.current_profile is None

    def test_stop_graceful_then_kill(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)

        with patch("subprocess.Popen", return_value=mock_proc):
            controller.start_recording()
            controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.stop_recording()

            # First SIGTERM, then SIGKILL
            assert mock_kill.call_count >= 2
            assert mock_kill.call_args_list[0] == ((100, signal.SIGTERM),)
            assert mock_kill.call_args_list[1] == ((100, signal.SIGKILL),)


# ---------------------------------------------------------------------------
# Replay saving (signals)
# ---------------------------------------------------------------------------


class TestReplaySaving:
    def test_save_replay_30s(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None

        # Inject mock proc directly to avoid monitor thread race
        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.save_replay(30)
            mock_kill.assert_called_once_with(100, signal.SIGRTMIN)

    def test_save_replay_60s(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None

        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.save_replay(60)
            mock_kill.assert_called_once_with(100, signal.SIGRTMIN + 1)

    def test_save_replay_300s(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None

        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.save_replay(300)
            mock_kill.assert_called_once_with(100, signal.SIGRTMIN + 2)

    def test_save_replay_unsupported_duration(
        self, controller: RecorderController
    ) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None

        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.save_replay(45)  # not in the map
            # Falls back to SIGRTMIN
            mock_kill.assert_called_once_with(100, signal.SIGRTMIN)

    def test_save_replay_process_dead(self, controller: RecorderController) -> None:
        """Saving when process is dead should not raise."""
        with patch("os.killpg") as mock_kill:
            controller.save_replay(30)
            mock_kill.assert_not_called()

    def test_take_screenshot(self, controller: RecorderController) -> None:
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None

        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("os.killpg") as mock_kill:
            controller.take_screenshot()
            mock_kill.assert_called_once_with(100, signal.SIGUSR1)

    def test_take_screenshot_process_dead(
        self, controller: RecorderController
    ) -> None:
        with patch("os.killpg") as mock_kill:
            controller.take_screenshot()
            mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# Signal mapping helper
# ---------------------------------------------------------------------------


class TestSignalMapping:
    def test_replay_signal_for_duration(self) -> None:
        assert replay_signal_for_duration(30) == 0
        assert replay_signal_for_duration(60) == 1
        assert replay_signal_for_duration(300) == 2
        assert replay_signal_for_duration(45) is None


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_crashed_process_restarts(self, controller: RecorderController) -> None:
        """When the monitor detects a crash, it should auto-restart."""
        mock_proc1 = MagicMock(spec=subprocess.Popen)
        mock_proc1.pid = 100
        mock_proc1.poll.return_value = None
        mock_proc1.wait.return_value = 1  # non-zero = crashed

        mock_proc2 = MagicMock(spec=subprocess.Popen)
        mock_proc2.pid = 200
        mock_proc2.poll.return_value = None
        # Block the second monitor thread from running
        mock_proc2.wait.return_value = 0

        # Inject mock proc directly — bypass start_recording() to avoid
        # background monitor thread races
        controller._proc = mock_proc1
        controller._stopped_intentionally = False

        with patch("subprocess.Popen", return_value=mock_proc2) as mock_popen:
            controller._monitor_process()

            # Should have spawned a new process
            assert controller._proc is mock_proc2
            # After restart, should NOT be intentionally stopped
            mock_popen.assert_called_once()

    def test_max_restarts_exceeded(self, controller: RecorderController) -> None:
        """After 3 crashes in 60s, give up and call on_crash."""
        crash_msgs: list[str] = []
        ctrl = RecorderController(
            output_dir="/tmp/test_videos",
            on_crash=lambda msg: crash_msgs.append(msg),
        )

        # Set up 3 recent crash timestamps
        now = time.monotonic()
        ctrl._restart_timestamps = [now - 10, now - 5, now - 2]

        # Spawn a process manually
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 1  # crashed

        ctrl._proc = mock_proc
        ctrl._stopped_intentionally = False

        with patch("subprocess.Popen") as mock_popen_restart:
            ctrl._monitor_process()
            # Should NOT have spawned a new process (max restarts exceeded)
            mock_popen_restart.assert_not_called()

        assert len(crash_msgs) >= 1
        assert "3 times" in crash_msgs[0]

    def test_explicit_stop_not_a_crash(self, controller: RecorderController) -> None:
        """When we intentionally stop, no restart happens."""
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 100
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = 0

        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with patch("subprocess.Popen") as mock_popen_restart:
            controller._monitor_process()
            mock_popen_restart.assert_not_called()


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestCommandBuilding:
    def test_build_command_defaults(self, tmp_path: Path) -> None:
        output = tmp_path / "replay.mkv"
        cmd = RecorderController._build_command(output)

        assert "gpu-screen-recorder" in cmd[0]
        assert "-w" in cmd
        assert "-f" in cmd
        assert "60" in cmd  # default fps
        assert "-r" in cmd
        assert "30" in cmd  # default duration
        assert str(output) in cmd

    def test_build_command_with_profile(
        self, tmp_path: Path, game_profile: GameProfile
    ) -> None:
        output = tmp_path / "replay.mkv"
        cmd = RecorderController._build_command(
            output,
            fps=game_profile.capture_fps,
            replay_duration=game_profile.replay_duration,
            audio_config=game_profile.audio_config,
        )

        assert "120" in cmd  # profile fps
        assert "45" in cmd   # profile duration
        assert "-a" in cmd
        assert "-q" in cmd   # mic device
        assert "-k" in cmd   # mic codec

    def test_build_command_no_audio_config(self, tmp_path: Path) -> None:
        output = tmp_path / "replay.mkv"
        cmd = RecorderController._build_command(output)

        # Default audio output
        assert "-a" in cmd
        assert "default_output" in cmd

    def test_start_fails_if_binary_missing(self, controller: RecorderController) -> None:
        with patch("subprocess.Popen", side_effect=FileNotFoundError("gpu-screen-recorder")):
            with pytest.raises(RecorderError, match="gpu-screen-recorder"):
                controller.start_recording()
