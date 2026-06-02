"""Tests for ui/services/global_hotkey.py — hotkey registration.

Mocks D-Bus and QShortcut. Never talks to a real D-Bus session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QWidget

from moment.ui.services.global_hotkey import GlobalHotkeyManager

pytestmark = [pytest.mark.gui]


@pytest.fixture
def parent_widget(qapp) -> QWidget:
    """Provide a clean QWidget parent, properly cleaned up after each test."""
    widget = QWidget()
    yield widget
    widget.close()
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_key(self) -> None:
        mgr = GlobalHotkeyManager()
        assert mgr.key_string == "Alt+Z"

    def test_custom_key(self) -> None:
        mgr = GlobalHotkeyManager(key="Ctrl+Shift+Z")
        assert mgr.key_string == "Ctrl+Shift+Z"

    def test_on_triggered_callback(self) -> None:
        called: list[int] = []

        mgr = GlobalHotkeyManager(on_triggered=lambda: called.append(1))
        mgr.triggered.emit()
        assert called == [1]

    def test_backend_none_before_register(self) -> None:
        mgr = GlobalHotkeyManager()
        assert mgr.backend is None


# ---------------------------------------------------------------------------
# KDE kglobalaccel (mocked)
# ---------------------------------------------------------------------------


class TestKDEBackend:
    def _mock_dbus_env(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        """Set up mocked D-Bus environment. Returns (mock_bus, mock_iface, mock_db)."""
        mock_component_iface = MagicMock()
        mock_component_iface.registerShortcut.return_value = None
        mock_component_iface.connect_to_signal.return_value = None

        mock_bus = MagicMock()
        mock_kg = MagicMock()
        mock_bus.get_object.return_value = mock_kg

        mock_dbus = MagicMock()
        mock_dbus.SessionBus.return_value = mock_bus
        mock_dbus.Interface.return_value = mock_component_iface
        # mock the exceptions submodule
        mock_dbus.exceptions.DBusException = Exception

        return mock_bus, mock_component_iface, mock_dbus

    def test_kde_registration(self, parent_widget: QWidget) -> None:
        """Mock D-Bus to simulate KDE registration success."""
        _mock_bus, _mock_iface, mock_dbus = self._mock_dbus_env()

        with (
            patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", True),
            patch("moment.ui.services.global_hotkey.DBusGMainLoop", create=True),
            patch("moment.ui.services.global_hotkey.dbus", mock_dbus, create=True),
        ):
            mgr = GlobalHotkeyManager(key="Alt+Z")
            backend = mgr.register(parent_widget)
            assert backend == "kde"
            assert mgr.backend == "kde"

    def test_kde_unregister(self, parent_widget: QWidget) -> None:
        _mock_bus, _mock_iface, mock_dbus = self._mock_dbus_env()

        with (
            patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", True),
            patch("moment.ui.services.global_hotkey.DBusGMainLoop", create=True),
            patch("moment.ui.services.global_hotkey.dbus", mock_dbus, create=True),
        ):
            mgr = GlobalHotkeyManager(key="Alt+Z")
            mgr.register(parent_widget)
            mgr.unregister()
            assert mgr.backend is None

    def test_kde_signal_triggers_callback(self, parent_widget: QWidget) -> None:
        triggered: list[int] = []
        _mock_bus, _mock_iface, mock_dbus = self._mock_dbus_env()

        with (
            patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", True),
            patch("moment.ui.services.global_hotkey.DBusGMainLoop", create=True),
            patch("moment.ui.services.global_hotkey.dbus", mock_dbus, create=True),
        ):
            mgr = GlobalHotkeyManager(key="Alt+Z", on_triggered=lambda: triggered.append(1))
            mgr.register(parent_widget)

            # Simulate the KDE signal handler
            mgr._dbus_shortcut_id = "moment_show_overlay"
            mgr._on_kde_shortcut_pressed("Moment", "moment_show_overlay")

            assert triggered == [1]

    def test_kde_ignores_other_shortcuts(self, parent_widget: QWidget) -> None:
        triggered: list[int] = []
        _mock_bus, _mock_iface, mock_dbus = self._mock_dbus_env()

        with (
            patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", True),
            patch("moment.ui.services.global_hotkey.DBusGMainLoop", create=True),
            patch("moment.ui.services.global_hotkey.dbus", mock_dbus, create=True),
        ):
            mgr = GlobalHotkeyManager(key="Alt+Z", on_triggered=lambda: triggered.append(1))
            mgr.register(parent_widget)

            mgr._dbus_shortcut_id = "moment_show_overlay"
            # Different shortcut ID should not trigger
            mgr._on_kde_shortcut_pressed("Moment", "other_shortcut")

            assert triggered == []

    def test_kde_extra_args_ignored(self, parent_widget: QWidget) -> None:
        """The signal handler accepts *args (3 D-Bus args) without error."""
        triggered: list[int] = []
        _mock_bus, _mock_iface, mock_dbus = self._mock_dbus_env()

        with (
            patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", True),
            patch("moment.ui.services.global_hotkey.DBusGMainLoop", create=True),
            patch("moment.ui.services.global_hotkey.dbus", mock_dbus, create=True),
        ):
            mgr = GlobalHotkeyManager(key="Alt+Z", on_triggered=lambda: triggered.append(1))
            mgr.register(parent_widget)

            mgr._dbus_shortcut_id = "moment_show_overlay"
            # Pass all 3 D-Bus args (componentName, shortcutName, shortcutValue)
            mgr._on_kde_shortcut_pressed("Moment", "moment_show_overlay", "Alt+Z,none,Alt+Z")

            assert triggered == [1]


# ---------------------------------------------------------------------------
# QShortcut fallback
# ---------------------------------------------------------------------------


class TestQShortcutFallback:
    def test_falls_back_when_no_dbus(self, parent_widget: QWidget) -> None:
        """With no D-Bus available, fall back to QShortcut."""
        with patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", False):
            mgr = GlobalHotkeyManager(key="Alt+Z")
            backend = mgr.register(parent_widget)
            assert backend == "shortcut"
            assert mgr.backend == "shortcut"

    def test_shortcut_activation(self, parent_widget: QWidget) -> None:
        triggered: list[int] = []

        with patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", False):
            mgr = GlobalHotkeyManager(key="Alt+Z", on_triggered=lambda: triggered.append(1))
            mgr.register(parent_widget)

            mgr._on_shortcut_activated()
            assert triggered == [1]

    def test_shortcut_unregister(self, parent_widget: QWidget) -> None:
        with patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", False):
            mgr = GlobalHotkeyManager(key="Alt+Z")
            mgr.register(parent_widget)
            mgr.unregister()
            assert mgr.backend is None


# ---------------------------------------------------------------------------
# update_key
# ---------------------------------------------------------------------------


class TestUpdateKey:
    def test_updates_key_string(self, parent_widget: QWidget) -> None:
        with patch("moment.ui.services.global_hotkey._DBUS_AVAILABLE", False):
            mgr = GlobalHotkeyManager(key="Alt+Z")
            mgr.register(parent_widget)
            mgr.update_key("Ctrl+Shift+Z", parent_widget)
            assert mgr.key_string == "Ctrl+Shift+Z"


# ---------------------------------------------------------------------------
# key_to_kde
# ---------------------------------------------------------------------------


class TestKeyConversion:
    def test_passthrough(self) -> None:
        assert GlobalHotkeyManager._key_to_kde("Alt+Z") == "Alt+Z"
        assert GlobalHotkeyManager._key_to_kde("Ctrl+Shift+F1") == "Ctrl+Shift+F1"
