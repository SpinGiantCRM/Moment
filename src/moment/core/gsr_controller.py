"""GSR controller — manages gpu-screen-recorder in instant-replay (-k) mode.

Launches GSR as a headless background service with ``-k`` (circular buffer).
SIGUSR1 triggers a buffer dump. Graceful shutdown with SIGTERM→SIGKILL.

The controller is thread-safe: all subprocess mutations are serialised via
an internal lock so the hotkey thread and watcher thread can safely interact.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess  # nosec B404 — required for external tool invocation
import threading
import time
from collections import deque
from pathlib import Path

from moment.utils.subprocess import Popen_sandboxed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GSR_BINARY = "gpu-screen-recorder"

# Default recording parameters (when no Config override)
DEFAULT_FPS = 60
DEFAULT_QUALITY = "very_high"
DEFAULT_CONTAINER = "mp4"
DEFAULT_REPLAY_DURATION = 120  # seconds of buffer

# SIGTERM grace period before SIGKILL
_TERM_GRACE = 5.0

# Max crash restarts within the rolling window
_MAX_RESTARTS = 3
_RESTART_WINDOW = 60.0  # seconds

# Debounce window for save_replay() — prevent buffer-dump spam
_SAVE_DEBOUNCE = 1.0


class GSRControllerError(RuntimeError):
    """Raised when the GSR process fails irrecoverably."""


class GSRController:
    """Manages a gpu-screen-recorder process in instant-replay (``-k``) mode.

    Thread-safe: all subprocess mutations go through an internal lock.

    Typical usage::

        ctrl = GSRController(
            output_dir="~/Videos/Moment",
            fps=60,
            quality="very_high",
            on_crash=lambda msg: print("GSR crashed:", msg),
        )
        ctrl.start()
        # ... user presses hotkey ...
        ctrl.save_replay()
        # ... on shutdown ...
        ctrl.stop()
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        output_dir: str | None = None,
        fps: int = DEFAULT_FPS,
        quality: str = DEFAULT_QUALITY,
        container: str = DEFAULT_CONTAINER,
        replay_duration: int = DEFAULT_REPLAY_DURATION,
        audio_device: str | None = None,
        record_area: str = "screen",
        show_cursor: bool = True,
        video_codec: str | None = None,
        on_crash: "callable[[str], None] | None" = None,
        on_file_ready: "callable[[Path], None] | None" = None,
    ) -> None:
        """Args:
            output_dir: Directory for buffer-dump files.
            fps: Capture frame rate.
            quality: GSR quality preset (``very_high``, ``high``, …).
            container: Output container (``mp4`` or ``mkv``).
            replay_duration: Circular buffer size in seconds.
            audio_device: Audio input device (``-a`` flag). None = no audio.
            record_area: ``-w`` flag value (``screen``, ``window``, etc.).
            show_cursor: Whether GSR renders the cursor (``--show-cursor``).
            video_codec: ``-v`` flag value (e.g. ``h264_nvenc``). None = auto.
            on_crash: Called as ``callback(message)`` when process dies
                irrecoverably.
            on_file_ready: Called as ``callback(path)`` when a replay file
                has been dumped and is ready for import.
        """
        self._output_dir = Path(
            os.path.expanduser(output_dir or "~/Videos/Moment")
        ).resolve()
        self._fps = fps
        self._quality = quality
        self._container = container
        self._replay_duration = replay_duration
        self._audio_device = audio_device
        self._record_area = record_area
        self._show_cursor = show_cursor
        self._video_codec = video_codec
        self._on_crash = on_crash
        self._on_file_ready = on_file_ready

        # Subprocess state
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

        # Crash tracking
        self._restart_timestamps: deque[float] = deque(maxlen=11)
        self._stopped_intentionally = False

        # Debounce
        self._last_save: float = 0.0

    # ------------------------------------------------------------------
    # Public API — lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch GSR in instant-replay mode.

        Creates the output directory if needed, spawns the GSR process,
        and starts the crash-monitor background thread.

        If GSR is already running it is stopped first.
        """
        # Check GSR binary availability
        if not shutil.which(GSR_BINARY):
            raise GSRControllerError(
                f"{GSR_BINARY} not found in PATH. "
                "Install gpu-screen-recorder to use replay mode."
            )

        with self._lock:
            if self._proc is not None:
                logger.info("Stopping existing GSR process before restart")
                self._stop_process_unlocked()

            self._stopped_intentionally = False
            self._output_dir.mkdir(parents=True, exist_ok=True)
            self._spawn_process_unlocked()

    def stop(self) -> None:
        """Gracefully stop GSR: SIGTERM → wait → SIGKILL."""
        with self._lock:
            self._stopped_intentionally = True
            self._stop_process_unlocked()

    def save_replay(self) -> None:
        """Trigger a buffer dump via SIGUSR1.

        Debounced: calls within 1 second of each other are ignored.
        """
        now = time.monotonic()
        if now - self._last_save < _SAVE_DEBOUNCE:
            logger.debug("save_replay() debounced — too soon since last save")
            return
        self._last_save = now

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Cannot save replay: GSR is not running")
                return

            pid = self._proc.pid
            if pid is None:
                logger.warning("Cannot save replay: no PID")
                return

            logger.info("Sending SIGUSR1 to GSR (pid=%d) to dump buffer", pid)
            try:
                os.kill(pid, signal.SIGUSR1)
            except (ProcessLookupError, OSError) as exc:
                logger.error("Failed to send SIGUSR1: %s", exc)

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """``True`` when the GSR process is alive."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def output_dir(self) -> Path:
        """Directory where buffer-dump files are written."""
        return self._output_dir

    @property
    def pid(self) -> int | None:
        """The GSR process PID, or ``None``."""
        with self._lock:
            return self._proc.pid if self._proc else None

    # ------------------------------------------------------------------
    # Internal — process management
    # ------------------------------------------------------------------

    def _build_command(self) -> list[str]:
        """Build the GSR command line for instant-replay mode."""
        cmd: list[str] = [
            GSR_BINARY,
            "-w", self._record_area,
            "-f", str(self._fps),
            "-c", self._container,
            "-q", self._quality,
            "-k",  # instant replay (circular buffer)
            "-o", str(self._output_dir),
        ]

        if self._video_codec:
            cmd.extend(["-v", self._video_codec])

        if self._audio_device:
            cmd.extend(["-a", self._audio_device])

        if self._show_cursor:
            cmd.append("--show-cursor")

        return cmd

    def _spawn_process_unlocked(self) -> None:
        """Spawn a new GSR subprocess.

        Caller MUST hold ``self._lock``.
        """
        cmd = self._build_command()
        logger.info("Starting GSR: %s", cmd)

        try:
            self._proc = Popen_sandboxed(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # os.setsid in child
            )
        except (OSError, FileNotFoundError) as exc:
            raise GSRControllerError(
                f"Failed to start {GSR_BINARY}: {exc}"
            ) from exc

        # Start crash-monitor thread
        t = threading.Thread(target=self._monitor_process, daemon=True)
        t.start()

    def _stop_process_unlocked(self) -> None:
        """Gracefully terminate the GSR subprocess.

        Caller MUST hold ``self._lock``.
        """
        if self._proc is None:
            return

        pid = self._proc.pid
        if pid is None:
            self._proc = None
            return

        logger.info("Stopping GSR (pid=%d) …", pid)

        # Send SIGTERM to the process group
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            self._proc = None
            return

        # Wait for graceful exit
        try:
            self._proc.wait(timeout=_TERM_GRACE)
            logger.info("GSR terminated gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("GSR did not exit; sending SIGKILL")
            try:
                os.kill(pid, signal.SIGKILL)
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
                logger.debug("GSR exited intentionally (code=%d)", returncode)
                return

            logger.warning("GSR crashed (code=%d)", returncode)
            self._proc = None

            if not self._can_restart():
                msg = (
                    f"GSR crashed {_MAX_RESTARTS}× in "
                    f"{_RESTART_WINDOW}s; giving up"
                )
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
            logger.info("Auto-restarting GSR …")
            try:
                self._spawn_process_unlocked()
            except GSRControllerError as exc:
                logger.error("Failed to restart GSR: %s", exc)
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
        """Check whether we're within the crash-restart budget."""
        self._restart_timestamps.append(time.monotonic())
        return len(self._restart_timestamps) <= _MAX_RESTARTS
