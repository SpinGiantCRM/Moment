"""Tests for ui/tray.py — TrayIcon with dynamic context menu."""

from __future__ import annotations

from moment.ui.tray import TrayIcon


class TestTrayIconInit:
    """Tests for TrayIcon construction."""

    def test_create(self, qapp) -> None:
        tray = TrayIcon()
        assert tray is not None
        assert tray._status == "Idle"
        assert tray._recording is False

    def test_starting_status(self, qapp) -> None:
        tray = TrayIcon()
        assert tray._status == "Idle"

    def test_recent_clips_empty_on_init(self, qapp) -> None:
        tray = TrayIcon()
        assert tray._recent_clips == []

    def test_has_icon(self, qapp) -> None:
        tray = TrayIcon()
        assert not tray._icon.isNull()


class TestTrayIconSignals:
    """Tests for TrayIcon signal definitions."""

    def test_signals_exist(self, qapp) -> None:
        tray = TrayIcon()
        assert hasattr(tray, "show_requested")
        assert hasattr(tray, "settings_requested")
        assert hasattr(tray, "quit_requested")
        assert hasattr(tray, "action_triggered")
        assert hasattr(tray, "recent_clicked")

    def test_show_requested_connectable(self, qapp) -> None:
        tray = TrayIcon()
        called = []
        tray.show_requested.connect(lambda: called.append(True))
        tray.show_requested.emit()
        assert called == [True]

    def test_action_triggered_connectable(self, qapp) -> None:
        tray = TrayIcon()
        called: list[str] = []
        tray.action_triggered.connect(lambda name: called.append(name))
        tray.action_triggered.emit("screenshot")
        assert called == ["screenshot"]

    def test_recent_clicked_connectable(self, qapp) -> None:
        tray = TrayIcon()
        called: list[str] = []
        tray.recent_clicked.connect(lambda stem: called.append(stem))
        tray.recent_clicked.emit("clip_123")
        assert called == ["clip_123"]


class TestTrayIconStatus:
    """Tests for status updates."""

    def test_update_status_changes_text(self, qapp) -> None:
        tray = TrayIcon()
        tray.update_status("Encoding clips…")
        assert tray._status == "Encoding clips…"

    def test_update_status_updates_tooltip(self, qapp) -> None:
        tray = TrayIcon()
        tray.update_status("Ready")
        tooltip = tray.toolTip()
        assert "Ready" in tooltip


class TestTrayIconRecentClips:
    """Tests for recent clips management."""

    def test_update_recent_stores_clips(self, qapp) -> None:
        tray = TrayIcon()
        clips = [("clip_1", "https://example.com/1"), ("clip_2", "https://example.com/2")]
        tray.update_recent(clips)
        assert len(tray._recent_clips) == 2

    def test_update_recent_caps_at_max(self, qapp) -> None:
        tray = TrayIcon()
        clips = [(f"clip_{i}", f"https://example.com/{i}") for i in range(10)]
        tray.update_recent(clips)
        assert len(tray._recent_clips) <= 3

    def test_update_recent_empty(self, qapp) -> None:
        tray = TrayIcon()
        tray.update_recent([])
        assert tray._recent_clips == []


class TestTrayIconRecordingState:
    """Tests for recording state toggle."""

    def test_set_recording_true(self, qapp) -> None:
        tray = TrayIcon()
        tray.set_recording(True)
        assert tray._recording is True

    def test_set_recording_false(self, qapp) -> None:
        tray = TrayIcon()
        tray.set_recording(True)
        tray.set_recording(False)
        assert tray._recording is False


class TestTrayIconMenu:
    """Tests for context menu construction."""

    def test_menu_exists_after_init(self, qapp) -> None:
        tray = TrayIcon()
        assert tray._menu is not None

    def test_menu_has_actions(self, qapp) -> None:
        tray = TrayIcon()
        actions = tray._menu.actions()
        assert len(actions) > 0

    def test_menu_has_open_action(self, qapp) -> None:
        tray = TrayIcon()
        texts = [a.text() for a in tray._menu.actions() if not a.isSeparator()]
        assert any("Moment" in t for t in texts)

    def test_menu_has_settings_action(self, qapp) -> None:
        tray = TrayIcon()
        texts = [a.text() for a in tray._menu.actions() if not a.isSeparator()]
        assert any("Settings" in t for t in texts), f"Settings not found in: {texts}"

    def test_menu_has_quit_action(self, qapp) -> None:
        tray = TrayIcon()
        texts = [a.text() for a in tray._menu.actions() if not a.isSeparator()]
        assert any("Quit" in t for t in texts)
