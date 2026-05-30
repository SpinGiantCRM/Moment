"""Recorder controller — manages gpu-screen-recorder as a managed subprocess.

Wraps gpu-screen-recorder with:
- Process lifecycle (start/stop/restart with crash recovery)
- Signal-based replay saving (SIGRTMIN family)
- Per-game profile switching
- Process group management (os.setsid) for clean signal delivery

For instant-replay mode (``-k`` flag), delegates to
:class:`~moment.core.gsr_controller.GSRController`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess  # nosec B404 — required for external tool invocation
import threading
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from moment.core.models import GameProfile
from moment.utils.subprocess import Popen_sandboxed
from moment.utils.system import validate_arg

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from moment.core.gsr_controller import GSRController

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Videos")
DEFAULT_REPLAY_DURATION = 30
DEFAULT_CAPTURE_FPS = 60

# Max crash restarts allowed within the rolling window
_MAX_RESTARTS = 3
_RESTART_WINDOW = 60.0  # seconds

# SIGTERM grace period before SIGKILL
_TERM_GRACE = 5.0

# Signal mapping: seconds → SIGRTMIN offset
_SIGNAL_MAP: dict[int, int] = {
    30: 0,     # SIGRTMIN
    60: 1,     # SIGRTMIN + 1
    300: 2,    # SIGRTMIN + 2
}


class RecorderError(RuntimeError):
    """Raised when the recorder process fails irrecoverably."""


class RecorderController:
    """Manages a gpu-screen-recorder subprocess.

    Thread-safe: all subprocess mutations are serialised via an internal
    lock so that the game-monitor thread and hotkey-daemon thread can
    safely interact with the recorder.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        output_dir: str | None = None,
        default_fps: int = DEFAULT_CAPTURE_FPS,
        default_duration: int = DEFAULT_REPLAY_DURATION,
        on_crash: Callable[[str], None] | None = None,
        on_file_ready: Callable[[Path], None] | None = None,
        gsr_controller: "GSRController | None" = None,
    ) -> None:
        """Args:
            output_dir: Directory where gpu-screen-recorder writes MKV
                files.  Defaults to ``~/Videos``.
            default_fps: Capture frame rate when no GameProfile overrides.
            default_duration: Default replay duration (seconds) for F8.
            on_crash: Called as ``callback(message)`` when the process
                crashes and cannot be restarted.
            on_file_ready: Called as ``callback(path)`` when a replay
                file has been saved and is ready for the pipeline.
            gsr_controller: Optional GSR instant-replay controller.
                When provided, ``save_replay()`` delegates to it.
        """
        self._output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser().resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._default_fps = default_fps
        self._default_duration = default_duration
        self._on_crash = on_crash
        self._on_file_ready = on_file_ready
        self._gsr_controller = gsr_controller

        # Subprocess state
        self._proc: subprocess.Popen[str] | None = None
        self._current_profile: GameProfile | None = None
        self._lock = threading.Lock()

        # Crash tracking
        self._restart_timestamps: deque[float] = deque(maxlen=11)

        # Whether the controller was explicitly stopped (vs crashed)
        self._stopped_intentionally = False

    # ------------------------------------------------------------------
    # Public API — lifecycle
    # ------------------------------------------------------------------

    def start_recording(self, profile: GameProfile | None = None) -> None:
        """Start (or restart) the gpu-screen-recorder subprocess.

        If a process is already running it is stopped first.

        Args:
            profile: Optional per-game profile with capture settings.
                If ``None``, defaults are used.
        """
        with self._lock:
            if self._proc is not None:
                logger.info("Stopping existing recorder before restart")
                self._stop_process_unlocked()

            self._stopped_intentionally = False
            self._current_profile = profile
            self._spawn_process_unlocked()

    def stop_recording(self) -> None:
        """Stop the recorder subprocess gracefully.

        Sends SIGTERM, waits up to 5 seconds, then SIGKILL if the process
        is still alive.
        """
        with self._lock:
            self._stopped_intentionally = True
            self._stop_process_unlocked()
            self._current_profile = None

    def save_replay(self, seconds: int = 30) -> None:
        """Tell gpu-screen-recorder to save the last *seconds* of replay.

        If a :class:`GSRController` is wired, delegates to its
        ``save_replay()`` (SIGUSR1). Otherwise sends the appropriate
        real-time signal to the process group.

        Args:
            seconds: Replay duration to save.  Must be one of the
                supported values (30, 60, or 300).
        """
        # Delegate to GSR controller when in instant-replay mode
        if self._gsr_controller is not None and self._gsr_controller.is_recording:
            logger.info("Delegating save_replay(%ds) to GSR controller", seconds)
            self._gsr_controller.save_replay()
            return

        signo = _SIGNAL_MAP.get(seconds)
        if signo is None:
            logger.warning("Unsupported replay duration %d; using default 30s", seconds)
            signo = 0  # SIGRTMIN

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Cannot save replay: recorder is not running")
                return

            try:
                pid = self._proc.pid
                sig = signal.SIGRTMIN + signo
                logger.info("Saving %ds replay → signal %d to pgid %d", seconds, sig, pid)
                os.killpg(pid, sig)
            except (ProcessLookupError, OSError) as exc:
                logger.error("Failed to send signal to recorder: %s", exc)

    def take_screenshot(self) -> None:
        """Trigger a screenshot via SIGUSR1 to the recorder process group."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Cannot take screenshot: recorder is not running")
                return

            try:
                pid = self._proc.pid
                logger.info("Taking screenshot → SIGUSR1 to pgid %d", pid)
                os.killpg(pid, signal.SIGUSR1)
            except (ProcessLookupError, OSError) as exc:
                logger.error("Failed to send screenshot signal: %s", exc)

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """``True`` when the recorder subprocess is alive."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def current_profile(self) -> GameProfile | None:
        """The active GameProfile, if any."""
        return self._current_profile

    @property
    def output_dir(self) -> Path:
        """Directory where MKV files are written."""
        if self._gsr_controller is not None:
            return self._gsr_controller.output_dir
        return self._output_dir

    @property
    def gsr_controller(self) -> "GSRController | None":
        """The wired GSR controller, if any."""
        return self._gsr_controller

    # ------------------------------------------------------------------
    # Internal — process management
    # ------------------------------------------------------------------

    def _spawn_process_unlocked(self) -> None:
        """Spawn a new gpu-screen-recorder subprocess.

        Caller MUST hold ``self._lock``.
        """
        profile = self._current_profile
        fps = profile.capture_fps if profile else self._default_fps
        replay = profile.replay_duration if profile else self._default_duration
        output = self._output_dir / "replay.mkv"

        cmd = self._build_command(
            output=output,
            fps=fps,
            replay_duration=replay,
            audio_config=profile.audio_config if profile else None,
        )

        logger.info("Starting recorder: %s", cmd)
        try:
            self._proc = Popen_sandboxed(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # → os.setsid in child
            )
        except (OSError, FileNotFoundError) as exc:
            raise RecorderError(f"Failed to start gpu-screen-recorder: {exc}") from exc

        # Start crash monitor thread
        t = threading.Thread(target=self._monitor_process, daemon=True)
        t.start()

    def _stop_process_unlocked(self) -> None:
        """Gracefully terminate the recorder subprocess.

        Caller MUST hold ``self._lock``.
        """
        if self._proc is None:
            return

        pid = self._proc.pid
        if pid is None:
            self._proc = None
            return

        logger.info("Stopping recorder (pid=%d) …", pid)

        # Send SIGTERM to the process group
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            self._proc = None
            return

        # Wait for graceful exit
        try:
            self._proc.wait(timeout=_TERM_GRACE)
            logger.info("Recorder terminated gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("Recorder did not exit; sending SIGKILL")
            try:
                os.killpg(pid, signal.SIGKILL)
                self._proc.wait(timeout=2)
            except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
                pass
        finally:
            self._proc = None

    def _monitor_process(self) -> None:
        """Background thread: watches for unexpected process death."""
        if self._proc is None:
            return

        try:
            returncode = self._proc.wait()
        except Exception as exc:
            logger.debug("Monitor thread wait() error: %s", exc)
            returncode = -1

        with self._lock:
            if self._stopped_intentionally:
                logger.debug("Recorder exited intentionally (code=%d)", returncode)
                return

            logger.warning("Recorder crashed (code=%d)", returncode)
            self._proc = None

            if not self._can_restart():
                msg = f"Recorder crashed {_MAX_RESTARTS} times in {_RESTART_WINDOW}s; giving up"
                logger.error(msg)
                cb = self._on_crash
                self._lock.release()
                try:
                    if cb is not None:
                        try:
                            cb(msg)
                        except Exception as exc:
                            logger.exception("on_crash callback error: %s", exc)
                finally:
                    self._lock.acquire()
                return

            # Auto-restart
            logger.info("Auto-restarting recorder …")
            try:
                self._spawn_process_unlocked()
            except RecorderError as exc:
                logger.error("Failed to restart: %s", exc)
                cb = self._on_crash
                self._lock.release()
                try:
                    if cb is not None:
                        try:
                            cb(str(exc))
                        except Exception as exc2:
                            logger.exception("on_crash callback error: %s", exc2)
                finally:
                    self._lock.acquire()

    def _can_restart(self) -> bool:
        """Check whether we're within the crash restart budget."""
        self._restart_timestamps.append(time.monotonic())
        return len(self._restart_timestamps) <= _MAX_RESTARTS

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_command(
        output: Path,
        fps: int = DEFAULT_CAPTURE_FPS,
        replay_duration: int = DEFAULT_REPLAY_DURATION,
        audio_config: dict[str, Any] | None = None,
    ) -> list[str]:
        """Build the gpu-screen-recorder command line.

        Args:
            output: MKV output path.
            fps: Capture frame rate.
            replay_duration: Default replay buffer size (seconds).
            audio_config: Optional dict with audio device settings.

        Returns:
            Tokenised command list.
        """
        cmd: list[str] = [
            "gpu-screen-recorder",
            "-w", "screen",           # capture entire screen
            "-f", str(fps),
            "-r", str(replay_duration),
            "-o", str(output),
        ]

        # Audio configuration
        if audio_config:
            game_device = audio_config.get("game_device", "")
            if game_device:
                cmd.extend(["-a", validate_arg(game_device, context="device")])
            mic_device = audio_config.get("mic_device", "")
            if mic_device:
                cmd.extend(["-q", validate_arg(mic_device, context="device")])
                # Bitrate and codec for mic
                cmd.extend([
                    "-k", audio_config.get("mic_codec", "opus"),
                    "-b", str(audio_config.get("mic_bitrate", "128k")),
                ])
        else:
            # Default: capture default audio output
            cmd.extend(["-a", "default_output"])

        return cmd


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def replay_signal_for_duration(seconds: int) -> int | None:
    """Return the SIGRTMIN offset for *seconds*, or ``None``."""
    return _SIGNAL_MAP.get(seconds)
