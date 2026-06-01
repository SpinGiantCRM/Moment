"""Tests for dialogs/about_dialog.py — keyboard shortcuts, license, credits."""

from __future__ import annotations
import pytest

from moment.ui.dialogs.about_dialog import _CREDITS, _SHORTCUTS, AboutDialog
pytestmark = [pytest.mark.gui]


class TestShortcutsData:
    """Tests for the shortcuts dataset."""

    def test_shortcuts_not_empty(self) -> None:

        assert len(_SHORTCUTS) > 0

    def test_shortcuts_have_valid_structure(self) -> None:
        for entry in _SHORTCUTS:
            assert len(entry) == 3
            cat, shortcut, action = entry
            assert isinstance(cat, str) and cat
            assert isinstance(shortcut, str) and shortcut
            assert isinstance(action, str) and action

class TestCreditsData:
    """Tests for the credits dataset."""

    def test_credits_not_empty(self) -> None:
        assert len(_CREDITS) > 0

    def test_credits_have_valid_structure(self) -> None:
        for entry in _CREDITS:
            assert len(entry) == 4
            group, lib, purpose, lic = entry
            assert isinstance(group, str) and group
            assert isinstance(lib, str) and lib
            assert isinstance(purpose, str) and purpose
            assert isinstance(lic, str) and lic

class TestAboutDialogInit:
    """Tests for AboutDialog construction."""

    def test_create(self, qapp) -> None:
        dlg = AboutDialog()
        assert dlg.windowTitle() == "About Moment"
        assert dlg._tabs.count() == 3

    def test_minimum_size(self, qapp) -> None:
        dlg = AboutDialog()
        assert dlg.minimumWidth() >= 300
        assert dlg.minimumHeight() >= 300

    def test_tab_labels(self, qapp) -> None:
        dlg = AboutDialog()
        labels = []
        for i in range(dlg._tabs.count()):
            labels.append(dlg._tabs.tabText(i))
        assert "Shortcuts" in labels[0] or "Keyboard" in labels[0]
        assert "License" in labels[1]
        assert "Credits" in labels[2]

    def test_shortcuts_tab_has_table(self, qapp) -> None:
        dlg = AboutDialog()
        tab = dlg._tabs.widget(0)
        assert tab is not None

    def test_license_tab_has_browser(self, qapp) -> None:
        dlg = AboutDialog()
        tab = dlg._tabs.widget(1)
        assert tab is not None

    def test_credits_tab_has_table(self, qapp) -> None:
        dlg = AboutDialog()
        tab = dlg._tabs.widget(2)
        assert tab is not None

    def test_close_button_accepts(self, qapp) -> None:
        dlg = AboutDialog()
        dlg.accept()
        assert dlg.result() == 1


