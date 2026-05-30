"""Hotkey daemon — global hotkey registration with multi-backend support.

Auto-detects the best available backend:
    1. SIGRTMIN-stub (always available — signals are handled by the
       recorder controller's process group)
    2. KDE D-Bus (``org.kde.kglobalaccel``)
    3. X11 (python-xlib Record extension)

Registered hotkeys:
    F8       → save 30s replay
    F9       → save 60s replay
    F10      → save 5min replay
    Ctrl+F8  → take screenshot
    Ctrl+F9  → bookmark current time

Hotkey actions are debounced (2-second cooldown per action) to prevent
I/O thrashing from rapid key repeats.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Debounce cooldown in seconds
DEBOUNCE_COOLDOWN = 2.0

# ---------------------------------------------------------------------------
# Action definitions
# ---------------------------------------------------------------------------


class HotkeyAction(Enum):
    """Actions that can be bound to global hotkeys."""

    SAVE_30S = auto()
    SAVE_60S = auto()
    SAVE_5MIN = auto()
    SCREENSHOT = auto()
    BOOKMARK = auto()


# Default key → action mapping
_DEFAULT_BINDINGS: dict[str, HotkeyAction] = {
    "F8": HotkeyAction.SAVE_30S,
    "F9": HotkeyAction.SAVE_60S,
    "F10": HotkeyAction.SAVE_5MIN,
    "Ctrl+F8": HotkeyAction.SCREENSHOT,
    "Ctrl+F9": HotkeyAction.BOOKMARK,
}


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class _Backend:
    """Abstract hotkey backend."""

    name: str = "unknown"

    def start(self) -> None:
        """Begin listening for hotkeys."""

    def stop(self) -> None:
        """Stop listening and release resources."""


class _SigrtminBackend(_Backend):
    """Stub backend that never registers OS-level hotkeys.

    This backend exists for platforms where true global hotkeys cannot
    be registered (e.g. Wayland without portal support).  The recorder
    controller's subprocess receives real-time signals directly via the
    application-level wiring.
    """

    name = "sigrtmin"

    def __init__(self) -> None:
        logger.info("SIGRTMIN-stub backend selected (hotkeys handled by recorder process)")

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _KdeBackend(_Backend):
    """Register hotkeys via KDE's ``org.kde.kglobalaccel`` D-Bus interface."""

    name = "kde"

    def __init__(self, bindings: dict[str, HotkeyAction]) -> None:
        self._bindings = bindings
        self._component: Any = None
        self._shortcut_ids: dict[str, str] = {}

    def start(self) -> None:
        try:
            import dbus  # type: ignore[import-untyped]
            from dbus.mainloop.glib import DBusGMainLoop  # type: ignore[import-untyped]
            DBusGMainLoop(set_as_default=True)

            bus = dbus.SessionBus()
            kglobal = bus.get_object(
                "org.kde.kglobalaccel",
                "/kglobalaccel",
            )
            component_iface = dbus.Interface(
                kglobal,
                "org.kde.kglobalaccel.Component",
            )

            component_name = "com.cliptray.moment"
            # Register the component
            self._component = component_iface

            for key, action in self._bindings.items():
                shortcut = self._key_to_kde(key)
                shortcut_id = f"moment_{action.name.lower()}"
                try:
                    component_iface.registerShortcut(
                        component_name,
                        shortcut_id,
                        shortcut,
                        shortcut,
                    )
                    self._shortcut_ids[shortcut_id] = shortcut
                except Exception as exc:
                    logger.warning("Failed to register shortcut %s: %s", shortcut_id, exc)

            logger.info(
                "KDE kglobalaccel backend: %d/%d shortcuts registered",
                len(self._shortcut_ids),
                len(self._bindings),
            )
        except ImportError:
            logger.debug("D-Bus/Python-dbus not available; falling back")
            raise RuntimeError("dbus not available")
        except Exception as exc:
            logger.warning("KDE backend failed: %s", exc)
            raise

    def stop(self) -> None:
        self._shortcut_ids.clear()
        self._component = None

    @staticmethod
    def _key_to_kde(key: str) -> str:
        """Convert a human-readable key to a KDE shortcut string.

        Examples:
            ``F8`` → ``\"F8\"``, ``Ctrl+F8`` → ``\"Ctrl+F8\"``
        """
        return key


class _X11Backend(_Backend):
    """Register hotkeys via X11 Record extension (python-xlib)."""

    name = "x11"

    def __init__(
        self,
        bindings: dict[str, HotkeyAction],
        dispatch: Callable[[HotkeyAction], None] | None = None,
    ) -> None:
        self._bindings = bindings
        self._dispatch_cb = dispatch
        self._display: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._listen,
            daemon=True,
            name="x11-hotkey",
        )
        self._thread.start()
        logger.info("X11 Record backend started (%d bindings)", len(self._bindings))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("X11 Record backend stopped")

    def _listen(self) -> None:
        """Main X11 event loop (runs in background thread)."""
        try:
            from Xlib import XK, X  # type: ignore[import-untyped]
            from Xlib.display import Display  # type: ignore[import-untyped]
            from Xlib.ext import record  # type: ignore[import-untyped]
            from Xlib.protocol import rq  # type: ignore[import-untyped]
        except ImportError:
            logger.debug("python-xlib not available; falling back")
            return

        self._display = Display()
        root = self._display.screen().root

        # Grab the keys we care about
        keycodes: dict[int, HotkeyAction] = {}
        for key_str, action in self._bindings.items():
            try:
                kc = _key_string_to_x11_keycode(self._display, key_str)
                if kc:
                    keycodes[kc] = action
                    root.grab_key(kc, _modifiers_for_x11(key_str), True, X.GrabModeAsync, X.GrabModeAsync)
            except Exception as exc:
                logger.warning("Cannot grab X11 key %s: %s", key_str, exc)

        self._display.flush()

        # Event loop
        while self._running:
            try:
                event = self._display.next_event()
                if event.type == X.KeyPress:
                    detail = event.detail
                    if detail in keycodes:
                        action = keycodes[detail]
                        self._dispatch(action)
            except Exception:
                if self._running:
                    logger.exception("X11 event loop error")
                    time.sleep(0.5)

    def _dispatch(self, action: HotkeyAction) -> None:
        """Fire the dispatch callback."""
        if self._dispatch_cb is not None:
            try:
                self._dispatch_cb(action)
            except Exception as exc:
                logger.exception("X11 dispatch callback error: %s", exc)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class HotkeyDaemon:
    """Manages global hotkey registration.

    Auto-detects the best available backend and exposes a callback
    interface for hotkey activation.

    Typical usage::

        daemon = HotkeyDaemon(on_triggered=handle_hotkey)
        daemon.start()
        # … later …
        daemon.stop()
    """

    def __init__(
        self,
        *,
        bindings: dict[str, HotkeyAction] | None = None,
        on_triggered: Callable[[HotkeyAction], None] | None = None,
    ) -> None:
        """Args:
            bindings: Override default key → action mappings.
            on_triggered: Called as ``callback(action)`` when a hotkey
                is pressed.  Debounced to a 2-second cooldown per action.
        """
        self._bindings = bindings or _DEFAULT_BINDINGS.copy()
        self._on_triggered = on_triggered
        self._backend: _Backend | None = None
        self._last_trigger: dict[HotkeyAction, float] = {}
        self._trigger_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> str:
        """Detect backend and begin listening for hotkeys.

        Returns:
            The name of the activated backend (e.g. ``\"sigrtmin\"``,
            ``\"kde\"``, ``\"x11\"``).
        """
        self._backend = _detect_backend(self._bindings, self._handle_action)
        logger.info("Hotkey daemon started (backend: %s)", self._backend_name())
        return self._backend_name()

    def stop(self) -> None:
        """Stop listening and release backend resources."""
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
            logger.info("Hotkey daemon stopped")

    @property
    def backend_name(self) -> str | None:
        """The name of the active backend, or ``None`` before ``start()``."""
        return self._backend_name()

    @property
    def is_running(self) -> bool:
        """``True`` when the daemon is active."""
        return self._backend is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _backend_name(self) -> str | None:
        if self._backend is not None:
            return self._backend.name
        return None

    def _handle_action(self, action: HotkeyAction) -> None:
        """Debounce and fire the on_triggered callback."""
        now = time.monotonic()
        with self._trigger_lock:
            last = self._last_trigger.get(action, 0)
            if now - last < DEBOUNCE_COOLDOWN:
                return
            self._last_trigger[action] = now

        logger.debug("Hotkey triggered: %s", action.name)
        if self._on_triggered is not None:
            try:
                self._on_triggered(action)
            except Exception as exc:
                logger.exception("on_triggered callback error: %s", exc)


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _detect_backend(
    bindings: dict[str, HotkeyAction],
    dispatch: Callable[[HotkeyAction], None],
) -> _Backend:
    """Probe available backends in preference order."""

    # 1. Try KDE
    try:
        backend = _KdeBackend(bindings)
        backend.start()
        logger.info("KDE backend active")
        return backend
    except Exception:  # nosec
        logger.debug("KDE backend unavailable; trying X11")

    # 2. Try X11 (dispatch wired via constructor)
    try:
        backend = _X11Backend(bindings, dispatch=dispatch)
        backend.start()
        logger.info("X11 backend active")
        return backend
    except Exception:
        logger.debug("X11 backend unavailable; falling back to SIGRTMIN stub")

    # 3. Fallback
    return _SigrtminBackend()


# ---------------------------------------------------------------------------
# X11 key helpers
# ---------------------------------------------------------------------------


def _modifiers_for_x11(key: str) -> int:
    """Extract modifier mask from a key string like ``\"Ctrl+F8\"``."""
    try:
        from Xlib import X  # type: ignore[import-untyped]
    except ImportError:
        return 0

    mask = 0
    parts = key.split("+")
    for mod in parts[:-1]:  # last part is the key itself
        m = mod.strip().lower()
        if m == "ctrl":
            mask |= X.ControlMask
        elif m in ("alt", "meta"):
            mask |= X.Mod1Mask
        elif m == "shift":
            mask |= X.ShiftMask
        elif m == "super":
            mask |= X.Mod4Mask
    return mask


def _key_string_to_x11_keycode(display: Any, key: str) -> int | None:
    """Convert a key string to an X11 keycode."""
    try:
        from Xlib import XK  # type: ignore[import-untyped]
    except ImportError:
        return None

    # Get the key name (last part after +)
    key_name = key.split("+")[-1].strip()

    # Map common key names to XK constants
    xk_name = key_name
    # XK_ prefix variants
    for prefix in ("XK_", ""):
        try:
            keysym = XK.string_to_keysym(f"{prefix}{key_name}")
            if keysym:
                return display.keysym_to_keycode(keysym)
        except Exception:  # nosec B110 — keysym lookup fallback is best-effort
            pass

    return None
