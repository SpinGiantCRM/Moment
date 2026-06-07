"""GSR controller — manages gpu-screen-recorder in instant-replay mode.

Launches GSR as a headless background service with ``-r`` (circular buffer).
SIGUSR1 / SIGRTMIN+* trigger buffer dumps. Graceful shutdown with
SIGTERM→SIGKILL.

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

# Processes from gpu-screen-recorder-ui that compete with Moment's overlay.
_GSR_UI_PROCESS_NAMES = (
    "gsr-ui",
    "gsr-global-hotkeys",
    "gsr-kwin-helper",
    "gsr-game-tracker",
    "gsr-wayland-bridge",
    "gsr-kms-server",
)

# Legacy overlay settings — no longer consumed by GSRController (handled in app.py).
_DEPRECATED_GSR_SETTINGS = frozenset({"hotkey_show_overlay", "overlay_auto_hide"})

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

# GSR 5.x replay save signals (man gpu-screen-recorder SIGNALS section)
_REPLAY_SIGNAL_OFFSETS: dict[int, int] = {
    30: 2,  # SIGRTMIN+2 → last 30 seconds
    60: 3,  # SIGRTMIN+3 → last 60 seconds
}

# ffmpeg / NVENC names → GSR ``-k`` codec values
_CODEC_MAP: dict[str, str] = {
    "auto": "auto",
    "h264": "h264",
    "h264_nvenc": "h264",
    "hevc": "hevc",
    "hevc_nvenc": "hevc",
    "av1": "av1",
    "av1_nvenc": "av1",
    "av1_10bit": "av1_10bit",
    "av1_10bit_nvenc": "av1_10bit",
    "hevc_hdr": "hevc_hdr",
    "av1_hdr": "av1_hdr",
    "vp8": "vp8",
    "vp9": "vp9",
}

# Settings UI record-area labels → GSR ``-w`` values
_RECORD_AREA_MAP: dict[str, str] = {
    "screen": "screen",
    "game": "screen",
    "desktop": "screen",
    "window": "focused",
    "focused": "focused",
    "monitor": "screen",
}


def map_record_area(value: str) -> str:
    """Map a config/UI record-area value to a GSR ``-w`` argument."""
    key = value.strip().lower()
    return _RECORD_AREA_MAP.get(key, value)


def map_video_codec(value: str | None) -> str:
    """Map ffmpeg-style codec names to GSR ``-k`` values."""
    if not value or not str(value).strip():
        return "auto"
    key = str(value).strip().lower()
    return _CODEC_MAP.get(key, key)


def replay_signal_for_duration(seconds: int | None) -> int:
    """Return the POSIX signal number to save *seconds* of replay buffer.

    Args:
        seconds: Requested clip length (30, 60, or None/other for full dump).

    Returns:
        ``signal.SIGUSR1`` for full-buffer dumps, else ``SIGRTMIN + offset``.
    """
    if seconds is None:
        return signal.SIGUSR1
    offset = _REPLAY_SIGNAL_OFFSETS.get(seconds)
    if offset is None:
        return signal.SIGUSR1
    return signal.SIGRTMIN + offset


class GSRControllerError(RuntimeError):
    """Raised when the GSR process fails irrecoverably."""


class GSRController:
    """Manages a gpu-screen-recorder process in instant-replay mode.

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
        ctrl.save_replay(30)
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
        record_area: ``-w`` flag value (``screen``, ``focused``, etc.).
        show_cursor: Whether GSR renders the cursor (``-cursor yes|no``).
        video_codec: ``-k`` flag value (e.g. ``h264``). None = auto.
        on_crash: Called as ``callback(message)`` when process dies
            irrecoverably.
        on_file_ready: Called as ``callback(path)`` when a replay file
            has been dumped and is ready for import.
        """
        self._output_dir = Path(os.path.expanduser(output_dir or "~/Videos/Moment")).resolve()
        self._fps = fps
        self._quality = quality
        self._container = container
        self._replay_duration = replay_duration
        self._audio_device = audio_device
        self._record_area = map_record_area(record_area)
        self._show_cursor = show_cursor
        self._video_codec = map_video_codec(video_codec)
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

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` when ``gpu-screen-recorder`` is on ``PATH``."""
        return shutil.which(GSR_BINARY) is not None

    @staticmethod
    def _notify_unavailable(message: str) -> None:
        """Log and surface a user-visible toast when GSR cannot start."""
        logger.warning(message)
        try:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "warning",
                "GPU Screen Recorder unavailable",
                message,
            )
        except Exception:
            logger.debug("Could not show GSR unavailable toast", exc_info=True)

    @staticmethod
    def _kill_processes_by_name(names: tuple[str, ...], *, label: str) -> int:
        """Send SIGTERM then SIGKILL to processes matching *names*.

        Returns:
            Number of processes signalled on the first pass.
        """
        import subprocess as _sp

        killed = 0
        for name in names:
            try:
                result = _sp.run(
                    ["pgrep", "-x", name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (FileNotFoundError, _sp.TimeoutExpired):
                continue

            if result.returncode != 0 or not result.stdout.strip():
                continue

            for pid_text in result.stdout.strip().splitlines():
                try:
                    pid = int(pid_text.strip())
                except ValueError:
                    continue
                logger.debug("Stopping %s (pid=%d)", name, pid)
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, OSError):
                    continue

        if killed == 0:
            return 0

        try:
            _sp.run(["sleep", str(_TERM_GRACE)], timeout=_TERM_GRACE + 1)
        except _sp.TimeoutExpired:
            logger.debug("Terminate grace period expired for %s", label)

        for name in names:
            try:
                remaining = _sp.run(
                    ["pgrep", "-x", name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (FileNotFoundError, _sp.TimeoutExpired):
                continue

            if remaining.returncode != 0 or not remaining.stdout.strip():
                continue

            for pid_text in remaining.stdout.strip().splitlines():
                try:
                    pid = int(pid_text.strip())
                    os.kill(pid, signal.SIGKILL)
                    logger.warning("Sent SIGKILL to %s (pid=%d)", name, pid)
                except (ProcessLookupError, OSError) as exc:
                    logger.debug("SIGKILL failed for %s (pid=%s): %s", name, pid_text, exc)

        return killed

    @staticmethod
    def _kill_external_gsr() -> None:
        """Kill any ``gpu-screen-recorder`` processes NOT managed by us."""
        count = GSRController._kill_processes_by_name((GSR_BINARY,), label="external GSR")
        if count:
            logger.info("Stopped %d external gpu-screen-recorder process(es)", count)

    @staticmethod
    def _stop_competing_gsr_ui() -> None:
        """Stop gpu-screen-recorder-ui helpers that own Alt+Z / ShadowPlay overlay."""
        count = GSRController._kill_processes_by_name(_GSR_UI_PROCESS_NAMES, label="GSR UI")
        if count:
            logger.info(
                "Stopped %d gpu-screen-recorder-ui helper(s) so Moment overlay can take over",
                count,
            )

    def start(self) -> None:
        """Launch GSR in instant-replay mode.

        Creates the output directory if needed, spawns the GSR process,
        and starts the crash-monitor background thread.

        Competing GSR UI helpers and external recorder instances are stopped
        first so Moment controls replay with the configured CLI flags.
        """
        if not self.is_available():
            msg = f"{GSR_BINARY} not found in PATH. Install gpu-screen-recorder to use replay mode."
            self._notify_unavailable(msg)
            raise GSRControllerError(msg)

        with self._lock:
            self._stop_competing_gsr_ui()
            self._kill_external_gsr()

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

    def save_replay(self, seconds: int | None = None) -> None:
        """Trigger a replay buffer dump.

        Uses GSR-native signals when possible:
        - 30s → ``SIGRTMIN+2``
        - 60s → ``SIGRTMIN+3``
        - other / None → ``SIGUSR1`` (full buffer up to ``-r``)

        Debounced: calls within 1 second of each other are ignored.

        Args:
            seconds: Requested clip length, or ``None`` for full buffer.
        """
        now = time.monotonic()
        if now - self._last_save < _SAVE_DEBOUNCE:
            logger.debug("save_replay() debounced — too soon since last save")
            return
        self._last_save = now

        sig = replay_signal_for_duration(seconds)

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Cannot save replay: GSR is not running")
                return

            pid = self._proc.pid
            if pid is None:
                logger.warning("Cannot save replay: no PID")
                return

            logger.info(
                "Sending signal %d to GSR (pid=%d) for %s replay save",
                sig,
                pid,
                f"{seconds}s" if seconds is not None else "full-buffer",
            )
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, OSError) as exc:
                logger.error("Failed to send replay signal: %s", exc)

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
        """Build the GSR 5.x command line for instant-replay mode."""
        cmd: list[str] = [
            GSR_BINARY,
            "-v",
            "no",
            "-w",
            self._record_area,
            "-f",
            str(self._fps),
            "-r",
            str(self._replay_duration),
            "-c",
            self._container,
            "-q",
            self._quality,
            "-k",
            self._video_codec,
            "-replay-storage",
            "ram",
            "-cursor",
            "yes" if self._show_cursor else "no",
            "-o",
            str(self._output_dir),
        ]

        if self._audio_device:
            cmd.extend(["-a", self._audio_device])

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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # os.setsid in child
            )
        except (OSError, FileNotFoundError) as exc:
            raise GSRControllerError(f"Failed to start {GSR_BINARY}: {exc}") from exc

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

        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError) as exc:
            logger.debug("SIGTERM failed for GSR (pid=%d): %s", pid, exc)
            self._proc = None
            return

        try:
            self._proc.wait(timeout=_TERM_GRACE)
            logger.info("GSR terminated gracefully")
        except subprocess.TimeoutExpired:
            logger.warning("GSR did not exit; sending SIGKILL")
            try:
                os.kill(pid, signal.SIGKILL)
                self._proc.wait(timeout=2)
            except (ProcessLookupError, OSError, subprocess.TimeoutExpired) as exc:
                logger.debug("SIGKILL/cleanup failed for GSR (pid=%d): %s", pid, exc)
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
                msg = f"GSR crashed {_MAX_RESTARTS}× in {_RESTART_WINDOW}s; giving up"
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
