"""Game monitor — detects game process state via /proc and nvidia-smi.

Scans ``/proc`` every 3 seconds for known game binary names.
Uses ``nvidia-smi`` GPU utilisation as a secondary signal.

States: IDLE → GAME_ACTIVE → GAME_EXITING
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 — required for external tool invocation
import threading
from typing import Callable

logger = logging.getLogger(__name__)

SCAN_INTERVAL = 3.0

# Known game binary names (configurable)
_DEFAULT_GAME_BINARIES: set[str] = {
    "cs2", "csgo", "dota2", "valorant", "r5apex.exe",
    "overwatch.exe", "FortniteClient-Win64-Shipping.exe",
    "RainbowSix.exe", "RocketLeague.exe", "EFT.exe",
    "GTA5.exe", "witcher3.exe", "Cyberpunk2077.exe",
    "bg3.exe", "VALORANT-Win64-Shipping.exe",
    "cs2.sh",  # native Linux
    "hl2_linux",  # Source engine
}


class GameMonitor:
    """Detects game sessions by scanning /proc and optionally nvidia-smi.

    Callbacks are fired on state transitions.  The monitor runs on
    a background timer thread.
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        game_binaries: set[str] | None = None,
        on_state_changed: Callable[[str, str | None], None] | None = None,
        scan_interval: float = SCAN_INTERVAL,
        use_nvidia_check: bool = True,
    ) -> None:
        """Args:
            game_binaries: Known game process names.  Defaults to a
                built-in list of common games.
            on_state_changed: Called as ``callback(state, game_name)``
                where *state* is ``"IDLE"``, ``"GAME_ACTIVE"``, or
                ``"GAME_EXITING"``.
            scan_interval: Seconds between /proc scans.
            use_nvidia_check: Whether to also check GPU utilisation.
        """
        self._binaries = game_binaries or _DEFAULT_GAME_BINARIES
        self._on_state_changed = on_state_changed
        self._interval = scan_interval
        self._use_nvidia = use_nvidia_check

        self._state: str = "IDLE"
        self._active_game: str | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False
        self._proc_warned: bool = False  # tracks whether we've already warned about restricted /proc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin monitoring game process state."""
        if self._running:
            return
        self._running = True
        self._scan()
        self._schedule()

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    @property
    def state(self) -> str:
        """Current game state: ``IDLE``, ``GAME_ACTIVE``, or ``GAME_EXITING``."""
        return self._state

    @property
    def active_game(self) -> str | None:
        """Name of the currently detected game, if any."""
        return self._active_game

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def game_binaries(self) -> set[str]:
        return self._binaries.copy()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._on_tick)
        self._timer.daemon = True
        self._timer.start()

    def _on_tick(self) -> None:
        try:
            self._scan()
        except Exception:
            logger.exception("Error during game monitor scan")
        finally:
            self._schedule()

    def _scan(self) -> None:
        """Scan /proc for known game processes."""
        self._check_proc_accessible()
        detected = self._find_game_process()

        with self._lock:
            prev_state = self._state

            if detected:
                if self._state == "IDLE":
                    self._state = "GAME_ACTIVE"
                    self._active_game = detected
                    logger.info("Game detected: %s → GAME_ACTIVE", detected)
                elif self._state == "GAME_ACTIVE" and self._active_game != detected:
                    # Different game started
                    old = self._active_game
                    self._active_game = detected
                    logger.info("Game switched: %s → %s", old, detected)
                elif self._state == "GAME_EXITING":
                    # Game came back? stay active
                    self._state = "GAME_ACTIVE"
                    self._active_game = detected
                    logger.info("Game resumed: %s → GAME_ACTIVE", detected)
            else:
                if self._state == "GAME_ACTIVE":
                    self._state = "GAME_EXITING"
                    logger.info("Game exited: %s → GAME_EXITING", self._active_game)
                elif self._state == "GAME_EXITING":
                    self._state = "IDLE"
                    self._active_game = None
                    logger.info("Post-game grace period ended → IDLE")

            # Fire callback on transition
            if self._state != prev_state and self._on_state_changed is not None:
                if self._state != "IDLE" or prev_state == "GAME_EXITING":
                    try:
                        self._on_state_changed(self._state, self._active_game)
                    except Exception as exc:
                        logger.exception("on_state_changed callback error: %s", exc)

    def _find_game_process(self) -> str | None:
        """Scan /proc for known game binaries.  Returns the process name or None."""
        try:
            for pid_dir in os.listdir("/proc"):
                if not pid_dir.isdigit():
                    continue
                comm_path = os.path.join("/proc", pid_dir, "comm")
                try:
                    with open(comm_path, "r") as fh:
                        comm = fh.read().strip()
                except (OSError, PermissionError):
                    continue

                if comm in self._binaries:
                    # Optionally cross-check with nvidia-smi
                    if self._use_nvidia and not self._check_gpu_utilization():
                        continue
                    return comm
        except (OSError, FileNotFoundError):
            pass

        return None

    def _check_proc_accessible(self) -> None:
        """Log a warning (once) if /proc is restricted (e.g. hidepid=2).

        Game detection depends on being able to read ``/proc/*/comm``.
        On hardened systems this may be denied — warn the user so they
        understand why game detection is silent.
        """
        if self._proc_warned:
            return
        self._proc_warned = True
        if not os.access("/proc/1/comm", os.R_OK):
            logger.warning(
                "Game detection disabled — /proc is restricted (hidepid=2). "
                "Run without `hidepid=2` mount option for game detection."
            )

    @staticmethod
    def _check_gpu_utilization() -> bool:
        """Use nvidia-smi to see if GPU is actively being used.

        Returns True if GPU utilisation > 0% (or if nvidia-smi is unavailable).
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )  # nosec
            if result.returncode != 0:
                return True  # Assume yes if we can't check
            util = int(result.stdout.strip())
            return util > 0
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return True  # Assume yes if we can't check
