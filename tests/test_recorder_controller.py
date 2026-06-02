"""Tests for core/recorder_controller.py — managed gpu-screen-recorder subprocess."""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.models import GameProfile
from moment.core.recorder_controller import (
    RecorderController,
    RecorderError,
    replay_signal_for_duration,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.integration]


@pytest.fixture
def controller(tmp_path: Path) -> RecorderController:
    return RecorderController(
        output_dir=str(tmp_path / "videos"),
        default_fps=60,
        default_duration=30,
    )


@pytest.fixture
def running_controller(controller: RecorderController) -> RecorderController:
    """A controller with a mock running subprocess."""

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    controller._proc = mock_proc
    return controller


# ---------------------------------------------------------------------------
# Replay signal helper
# ---------------------------------------------------------------------------


class TestReplaySignalForDuration:
    def test_known_durations(self) -> None:
        assert replay_signal_for_duration(30) == 0
        assert replay_signal_for_duration(60) == 1
        assert replay_signal_for_duration(300) == 2

    def test_unknown_duration(self) -> None:
        assert replay_signal_for_duration(120) is None
        assert replay_signal_for_duration(0) is None
        assert replay_signal_for_duration(-1) is None


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_output_dir_created(self, tmp_path: Path) -> None:
        d = tmp_path / "recordings"
        RecorderController(output_dir=str(d))
        assert d.exists()

    def test_default_output_dir(self) -> None:
        with patch("moment.core.recorder_controller.DEFAULT_OUTPUT_DIR", "/tmp/moment-test"):
            rc = RecorderController()
            assert rc.output_dir is not None

    def test_default_values(self, controller: RecorderController) -> None:
        assert controller._default_fps == 60
        assert controller._default_duration == 30

    def test_not_recording_initially(self, controller: RecorderController) -> None:
        assert controller.is_recording is False

    def test_no_current_profile_initially(self, controller: RecorderController) -> None:
        assert controller.current_profile is None

    def test_no_gsr_controller_initially(self, controller: RecorderController) -> None:
        assert controller.gsr_controller is None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_output_dir_with_gsr_controller(self, tmp_path: Path) -> None:
        mock_gsr = MagicMock()
        gsr_dir = tmp_path / "gsr_output"
        mock_gsr.output_dir = gsr_dir
        rc = RecorderController(gsr_controller=mock_gsr)
        assert rc.output_dir == gsr_dir

    def test_output_dir_without_gsr(self, controller: RecorderController) -> None:
        assert "videos" in str(controller.output_dir).lower()

    def test_is_recording_running(self, running_controller: RecorderController) -> None:
        assert running_controller.is_recording is True

    def test_is_recording_no_proc(self, controller: RecorderController) -> None:
        assert controller.is_recording is False

    def test_current_profile(self, controller: RecorderController) -> None:
        profile = GameProfile(id="gp1", game_name="cs2", display_name="CS2")
        controller._current_profile = profile
        assert controller.current_profile == profile


# ---------------------------------------------------------------------------
# Start recording
# ---------------------------------------------------------------------------


class TestStartRecording:
    def test_spawns_process(self, controller: RecorderController) -> None:
        with (
            patch.object(controller, "_spawn_process_unlocked") as mock_spawn,
            patch("threading.Thread"),
        ):
            controller.start_recording()
            mock_spawn.assert_called_once()

    def test_stops_existing_before_start(self, controller: RecorderController) -> None:
        controller._proc = MagicMock()
        with (
            patch.object(controller, "_spawn_process_unlocked") as mock_spawn,
            patch.object(controller, "_stop_process_unlocked") as mock_stop,
            patch("threading.Thread"),
        ):
            controller.start_recording()
            mock_stop.assert_called_once()
            mock_spawn.assert_called_once()

    def test_stores_profile(self, controller: RecorderController) -> None:
        profile = GameProfile(id="gp2", game_name="valorant", display_name="Valorant")
        with (
            patch.object(controller, "_spawn_process_unlocked"),
            patch("threading.Thread"),
        ):
            controller.start_recording(profile=profile)
            assert controller.current_profile == profile


# ---------------------------------------------------------------------------
# Stop recording
# ---------------------------------------------------------------------------


class TestStopRecording:
    def test_stops_process(self, controller: RecorderController) -> None:
        controller._proc = MagicMock()
        controller._proc.pid = 999
        controller._proc.poll.return_value = None
        with (
            patch("os.killpg"),
            patch.object(controller._proc, "wait"),
        ):
            controller.stop_recording()
            assert controller.current_profile is None

    def test_stop_without_proc(self, controller: RecorderController) -> None:
        controller.stop_recording()  # Should not raise

    def test_sets_intentional_stop(self, controller: RecorderController) -> None:
        controller._proc = MagicMock()
        controller._proc.pid = 888
        controller._proc.poll.return_value = None
        with (
            patch("os.killpg"),
            patch.object(controller._proc, "wait"),
        ):
            controller.stop_recording()
            assert controller._stopped_intentionally is True


# ---------------------------------------------------------------------------
# Save replay
# ---------------------------------------------------------------------------


class TestSaveReplay:
    def test_delegates_to_gsr_when_recording(self, controller: RecorderController) -> None:
        mock_gsr = MagicMock()
        mock_gsr.is_recording = True
        controller._gsr_controller = mock_gsr

        controller.save_replay(30)
        mock_gsr.save_replay.assert_called_once()

    def test_sends_signal_to_process(self, running_controller: RecorderController) -> None:
        with patch("os.killpg") as mock_killpg:
            running_controller.save_replay(30)
            mock_killpg.assert_called_once()
            args = mock_killpg.call_args[0]
            assert args[0] == 12345
            assert args[1] == signal.SIGRTMIN

    def test_unsupported_duration_uses_default(
        self,
        running_controller: RecorderController,
    ) -> None:
        with patch("os.killpg") as mock_killpg:
            running_controller.save_replay(120)  # not in _SIGNAL_MAP
            mock_killpg.assert_called_once()
            args = mock_killpg.call_args[0]
            assert args[1] == signal.SIGRTMIN  # falls back to 0

    def test_noop_when_not_running(self, controller: RecorderController) -> None:
        with patch("os.killpg") as mock_killpg:
            controller.save_replay(30)
            mock_killpg.assert_not_called()

    def test_noop_when_proc_dead(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # exited
        controller._proc = mock_proc
        with patch("os.killpg") as mock_killpg:
            controller.save_replay(30)
            mock_killpg.assert_not_called()

    def test_killpg_error_handled(self, running_controller: RecorderController) -> None:
        with patch("os.killpg", side_effect=ProcessLookupError("no process")):
            running_controller.save_replay(30)  # Should not raise


# ---------------------------------------------------------------------------
# Take screenshot
# ---------------------------------------------------------------------------


class TestTakeScreenshot:
    def test_sends_sigusr1(self, running_controller: RecorderController) -> None:
        with patch("os.killpg") as mock_killpg:
            running_controller.take_screenshot()
            mock_killpg.assert_called_once()
            args = mock_killpg.call_args[0]
            assert args[0] == 12345
            assert args[1] == signal.SIGUSR1

    def test_noop_when_not_running(self, controller: RecorderController) -> None:
        with patch("os.killpg") as mock_killpg:
            controller.take_screenshot()
            mock_killpg.assert_not_called()

    def test_error_handled(self, running_controller: RecorderController) -> None:
        with patch("os.killpg", side_effect=ProcessLookupError):
            running_controller.take_screenshot()  # Should not raise


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_basic_command(self) -> None:
        cmd = RecorderController._build_command(
            output=Path("/tmp/out.mkv"),
            fps=60,
            replay_duration=30,
        )
        assert "gpu-screen-recorder" in cmd
        assert "-f" in cmd
        assert "60" in cmd
        assert "-r" in cmd
        assert "30" in cmd
        assert "-o" in cmd
        assert "/tmp/out.mkv" in cmd
        assert "-a" in cmd
        assert "default_output" in cmd

    def test_with_audio_config(self) -> None:
        audio = {
            "game_device": "alsa_output.pci-0000_00_1f.3.analog-stereo",
            "mic_device": "alsa_input.usb-Mic_-1.analog-mono",
            "mic_codec": "opus",
            "mic_bitrate": "128k",
        }
        cmd = RecorderController._build_command(
            output=Path("/tmp/out.mkv"),
            fps=60,
            replay_duration=30,
            audio_config=audio,
        )
        assert "-a" in cmd
        assert any("alsa_output" in a for a in cmd)
        assert "-q" in cmd
        assert any("alsa_input" in a for a in cmd)
        assert "-k" in cmd
        assert "opus" in cmd
        assert "-b" in cmd
        assert "128k" in cmd

    def test_audio_config_without_mic(self) -> None:
        audio = {
            "game_device": "default",
            "mic_device": "",
        }
        cmd = RecorderController._build_command(
            output=Path("/tmp/out.mkv"),
            audio_config=audio,
        )
        assert "-a" in cmd
        assert "default" in cmd
        assert "-q" not in cmd


# ---------------------------------------------------------------------------
# _spawn_process_unlocked
# ---------------------------------------------------------------------------


class TestSpawnProcess:
    def test_spawn_with_profile(self, controller: RecorderController, tmp_path: Path) -> None:
        profile = GameProfile(
            id="gp3",
            game_name="cs2",
            display_name="CS2",
            capture_fps=120,
            replay_duration=60,
        )
        controller._current_profile = profile
        with (
            patch("moment.core.recorder_controller.Popen_sandboxed") as mock_popen,
            patch("threading.Thread"),
        ):
            controller._spawn_process_unlocked()
            mock_popen.assert_called_once()

    def test_spawn_without_profile(self, controller: RecorderController) -> None:
        with (
            patch("moment.core.recorder_controller.Popen_sandboxed") as mock_popen,
            patch("threading.Thread"),
        ):
            controller._spawn_process_unlocked()
            mock_popen.assert_called_once()

    def test_spawn_oserror_raises(self, controller: RecorderController) -> None:
        with (
            patch(
                "moment.core.recorder_controller.Popen_sandboxed",
                side_effect=FileNotFoundError("not found"),
            ),
            patch("threading.Thread"),
        ):
            with pytest.raises(RecorderError, match="Failed to start"):
                controller._spawn_process_unlocked()


# ---------------------------------------------------------------------------
# _stop_process_unlocked
# ---------------------------------------------------------------------------


class TestStopProcess:
    def test_none_proc_noop(self, controller: RecorderController) -> None:
        controller._stop_process_unlocked()  # Should not raise

    def test_sends_sigterm(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 777
        controller._proc = mock_proc
        with (
            patch("os.killpg") as mock_killpg,
            patch.object(mock_proc, "wait"),
        ):
            controller._stop_process_unlocked()
            mock_killpg.assert_called_with(777, signal.SIGTERM)
            assert controller._proc is None

    def test_killpg_oserror_noop(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 666
        controller._proc = mock_proc
        with patch("os.killpg", side_effect=ProcessLookupError):
            controller._stop_process_unlocked()
            assert controller._proc is None

    def test_timeout_sends_sigkill(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 555
        mock_proc.poll.return_value = None
        controller._proc = mock_proc

        import subprocess as _sp

        with (
            patch("os.killpg") as mock_killpg,
            patch.object(mock_proc, "wait", side_effect=[_sp.TimeoutExpired("cmd", 5), None]),
        ):
            controller._stop_process_unlocked()
            # Should have sent SIGKILL after timeout
            sigkill_calls = [c for c in mock_killpg.call_args_list if c[0][1] == signal.SIGKILL]
            assert len(sigkill_calls) >= 1

    def test_pid_is_none(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = None
        controller._proc = mock_proc
        controller._stop_process_unlocked()
        assert controller._proc is None


# ---------------------------------------------------------------------------
# _can_restart
# ---------------------------------------------------------------------------


class TestCanRestart:
    def test_can_restart_initially(self, controller: RecorderController) -> None:
        assert controller._can_restart() is True

    def test_can_restart_after_max(self, controller: RecorderController) -> None:
        for _ in range(4):  # _MAX_RESTARTS = 3, so 4th call returns False
            controller._can_restart()
        assert controller._can_restart() is False


# ---------------------------------------------------------------------------
# crash recovery
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_monitor_crash_triggers_restart(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1  # crash
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=True),
            patch.object(controller, "_spawn_process_unlocked") as mock_spawn,
        ):
            controller._monitor_process()
            mock_spawn.assert_called_once()

    def test_monitor_crash_no_restart(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=False),
            patch.object(controller, "_spawn_process_unlocked") as mock_spawn,
        ):
            controller._monitor_process()
            mock_spawn.assert_not_called()

    def test_monitor_intentional_stop(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        controller._proc = mock_proc
        controller._stopped_intentionally = True

        with (
            patch.object(controller, "_spawn_process_unlocked") as mock_spawn,
        ):
            controller._monitor_process()
            mock_spawn.assert_not_called()

    def test_monitor_crash_callback(self, controller: RecorderController) -> None:
        crash_msgs: list[str] = []
        controller._on_crash = lambda msg: crash_msgs.append(msg)

        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=False),
        ):
            controller._monitor_process()
            assert any("crashed" in msg.lower() for msg in crash_msgs)

    def test_monitor_crash_callback_error_handled(self, controller: RecorderController) -> None:
        def bad_cb(msg: str) -> None:
            raise RuntimeError("callback error")

        controller._on_crash = bad_cb
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=False),
        ):
            controller._monitor_process()  # Should not raise

    def test_monitor_wait_exception(self, controller: RecorderController) -> None:
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = RuntimeError("wait failed")
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=False),
        ):
            controller._monitor_process()  # Should not raise

    def test_restart_error_callback(self, controller: RecorderController) -> None:
        crash_msgs: list[str] = []
        controller._on_crash = lambda msg: crash_msgs.append(msg)

        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1
        controller._proc = mock_proc
        controller._stopped_intentionally = False

        with (
            patch.object(controller, "_can_restart", return_value=True),
            patch.object(controller, "_spawn_process_unlocked", side_effect=RecorderError("boom")),
        ):
            controller._monitor_process()
            assert any("boom" in msg for msg in crash_msgs)

    def test_no_proc_noop(self, controller: RecorderController) -> None:
        assert controller._proc is None
        controller._monitor_process()  # Should not raise


# ---------------------------------------------------------------------------
# GSR controller delegation
# ---------------------------------------------------------------------------


class TestGSRDelegation:
    def test_output_dir_delegates(self, tmp_path: Path) -> None:
        mock_gsr = MagicMock()
        gsr_dir = tmp_path / "gsr_output"
        mock_gsr.output_dir = gsr_dir
        mock_gsr.is_recording = True
        rc = RecorderController(gsr_controller=mock_gsr)
        assert rc.output_dir == gsr_dir

    def test_gsr_controller_property(self, tmp_path: Path) -> None:
        mock_gsr = MagicMock()
        rc = RecorderController(gsr_controller=mock_gsr)
        assert rc.gsr_controller == mock_gsr

    def test_gsr_controller_none_by_default(self) -> None:
        rc = RecorderController()
        assert rc.gsr_controller is None
