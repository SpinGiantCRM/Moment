"""Global hotkey manager — D-Bus kglobalaccel (KDE) + QShortcut fallback.

Priorities:
    1. KDE global shortcuts via ``org.kde.kglobalaccel`` D-Bus interface.
       These fire **before** any other listener (including GSR's own
       hotkey), so Moment can intercept ``Alt+Z`` before GSR's GTK
       overlay appears.
    2. QShortcut fallback (window-focused only). On non-KDE desktops
       (GNOME, Sway, etc.) the overlay only appears when the Moment
       window has focus.

On KDE the registration order guarantees Moment receives ``Alt+Z``
first. GSR's built-in hotkey never fires.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

logger = logging.getLogger(__name__)

# D-Bus availability
try:
    import dbus  # type: ignore[import-untyped]
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore[import-untyped]

    _DBUS_AVAILABLE = True
except ImportError:
    _DBUS_AVAILABLE = False
    logger.debug("D-Bus/Python-dbus not available")


class GlobalHotkeyManager(QObject):
    """Registers a single global hotkey, preferring kglobalaccel on KDE.

    Emits ``triggered`` when the hotkey is pressed (from any backend).

    Typical usage::

        mgr = GlobalHotkeyManager(key="Alt+Z", on_triggered=show_overlay)
        backend = mgr.register()   # → "kde" or "shortcut"
        # … later …
        mgr.unregister()
    """

    triggered = pyqtSignal()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        key: str = "Alt+Z",
        on_triggered: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Args:
        key: The hotkey string (e.g. ``"Alt+Z"``).
        on_triggered: Called (no args) when the hotkey fires.
        parent: Qt parent object.
        """
        super().__init__(parent)
        self._key = key
        self._backend_name: str | None = None
        self._dbus_component: str | None = None
        self._dbus_shortcut_id: str | None = None
        self._qshortcut: QShortcut | None = None
        self._qshortcut_parent: QObject | None = None

        if on_triggered is not None:
            self.triggered.connect(on_triggered)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, parent_widget: QObject | None = None) -> str:
        """Register the hotkey with the best available backend.

        Args:
            parent_widget: A QObject parent for the QShortcut fallback.
                Required for the fallback to work.

        Returns:
            The backend name: ``"kde"`` or ``"shortcut"``.

        Raises:
            RuntimeError: If ``parent_widget`` is ``None`` and the
                fallback path is taken.
        """
        self._qshortcut_parent = parent_widget

        # Try KDE kglobalaccel first
        if self._try_register_kde():
            self._backend_name = "kde"
            logger.info("Global hotkey '%s' registered via KDE kglobalaccel", self._key)
            return "kde"

        # Fallback to QShortcut
        self._backend_name = "shortcut"
        if parent_widget is None:
            logger.warning("No parent widget for QShortcut fallback")
        else:
            self._qshortcut = QShortcut(QKeySequence(self._key), parent_widget)
            self._qshortcut.activated.connect(self._on_shortcut_activated)
            logger.info(
                "Global hotkey '%s' registered via QShortcut (window-focused only)",
                self._key,
            )
        return "shortcut"

    def unregister(self) -> None:
        """Clean up the hotkey registration."""
        if self._backend_name == "kde":
            self._unregister_kde()
        if self._qshortcut is not None:
            self._qshortcut.activated.disconnect(self._on_shortcut_activated)
            self._qshortcut = None
        self._backend_name = None
        logger.info("Global hotkey '%s' unregistered", self._key)

    @property
    def backend(self) -> str | None:
        """The active backend name or ``None`` before ``register()``."""
        return self._backend_name

    @property
    def key_string(self) -> str:
        """The configured hotkey string."""
        return self._key

    def update_key(self, new_key: str, parent_widget: QObject | None = None) -> None:
        """Change the hotkey and re-register.

        Args:
            new_key: New key string (e.g. ``"Ctrl+Shift+Z"``).
            parent_widget: Widget for QShortcut fallback.
        """
        was_registered = self._backend_name is not None
        if was_registered:
            self.unregister()
        self._key = new_key
        self._qshortcut_parent = parent_widget
        if was_registered:
            self.register(parent_widget)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_shortcut_activated(self) -> None:
        """QShortcut activated → emit triggered."""
        logger.debug("QShortcut triggered: %s", self._key)
        self.triggered.emit()

    # ------------------------------------------------------------------
    # KDE kglobalaccel backend
    # ------------------------------------------------------------------

    def _try_register_kde(self) -> bool:
        """Attempt to register via kglobalaccel D-Bus.

        Returns ``True`` on success.
        """
        if not _DBUS_AVAILABLE:
            logger.debug("D-Bus not available; skipping kglobalaccel")
            return False

        try:
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

            self._dbus_component = "Moment"
            self._dbus_shortcut_id = "moment_show_overlay"

            # kded global shortcut format is "Alt+Z"
            shortcut = self._key_to_kde(self._key)

            try:
                component_iface.registerShortcut(
                    self._dbus_component,
                    self._dbus_shortcut_id,
                    shortcut,
                    shortcut,
                )
            except Exception as exc:
                logger.warning(
                    "kglobalaccel registerShortcut failed: %s",
                    exc,
                )
                return False

            # Connect to the signal so we know when the shortcut is activated
            component_iface.connect_to_signal(
                "shortcutPressed",
                self._on_kde_shortcut_pressed,
            )
            return True

        except dbus.exceptions.DBusException as exc:
            logger.debug(
                "kglobalaccel not available (not on KDE?): %s",
                exc,
            )
            return False
        except Exception as exc:
            logger.warning("kglobalaccel registration failed: %s", exc)
            return False

    def _unregister_kde(self) -> None:
        """Remove the kglobalaccel shortcut."""
        if not _DBUS_AVAILABLE or self._dbus_component is None:
            return

        try:
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
            component_iface.unregisterShortcut(
                self._dbus_component,
                self._dbus_shortcut_id or "moment_show_overlay",
            )
            logger.debug("kglobalaccel shortcut unregistered")
        except Exception as exc:
            logger.debug("kglobalaccel unregister failed (non-fatal): %s", exc)
        finally:
            self._dbus_component = None
            self._dbus_shortcut_id = None

    def _on_kde_shortcut_pressed(
        self, component_name: str, shortcut_id: str, *_args: object
    ) -> None:
        """kglobalaccel signal handler — fired when shortcut is activated.

        The D-Bus signal passes 3 args (componentName, shortcutName,
        shortcutValue). We accept *args to be forward-compatible.
        """
        logger.debug(
            "KDE shortcut pressed: component=%s shortcut=%s",
            component_name,
            shortcut_id,
        )
        if shortcut_id == self._dbus_shortcut_id:
            self.triggered.emit()

    @staticmethod
    def _key_to_kde(key: str) -> str:
        """Convert a key string to KDE global shortcut format.

        KDE uses the same format as Qt key sequences, so this is a
        pass-through.
        """
        return key
