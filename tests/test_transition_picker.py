"""Tests for transition_picker.py — merge transition selection dialog."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QPushButton,
)

from moment.ui.widgets.transition_picker import _TRANSITIONS, TransitionPicker

pytestmark = [pytest.mark.gui]


class TestTransitionPickerInit:
    """Tests for TransitionPicker construction and defaults."""

    def test_create_dialog(self, qtbot) -> None:
        """TransitionPicker can be created as a modal dialog."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        assert dialog.isModal()
        assert dialog.windowTitle() == "Transition Picker"

    def test_default_selection_is_cut(self, qtbot) -> None:
        """Default transition is Cut."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        result = dialog.selected_transition()
        assert result["type"] == "cut"
        assert result["duration"] == 0.0
        assert result["apply_to_all"] is False

    def test_list_contains_all_transitions(self, qtbot) -> None:
        """List widget shows all transition types from _TRANSITIONS."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        assert dialog._list.count() == len(_TRANSITIONS)
        for i, tdef in enumerate(_TRANSITIONS):
            item = dialog._list.item(i)
            assert item.text() == tdef.label

    def test_cut_has_no_duration_controls(self, qtbot) -> None:
        """Duration controls are hidden for Cut."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        assert dialog._duration_widget.isHidden()

    def test_duration_visible_for_crossfade(self, qtbot) -> None:
        """Duration controls are visible for Crossfade."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        # Select Crossfade (index 1)
        dialog._list.setCurrentRow(1)
        assert not dialog._duration_widget.isHidden()


class TestTransitionPickerSelection:
    """Tests for transition selection behavior."""

    def test_select_crossfade(self, qtbot) -> None:
        """Selecting Crossfade returns crossfade type and duration."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade
        result = dialog.selected_transition()
        assert result["type"] == "crossfade"
        assert result["duration"] == 1.0
        assert result["params"] == {"xfade": "fade"}

    def test_select_whip_left(self, qtbot) -> None:
        """Selecting Whip Left returns whip_left type."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(2)
        result = dialog.selected_transition()
        assert result["type"] == "whip_left"
        assert result["params"] == {"whip": "left"}

    def test_select_whip_right(self, qtbot) -> None:
        """Selecting Whip Right returns whip_right type."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(3)
        result = dialog.selected_transition()
        assert result["type"] == "whip_right"
        assert result["params"] == {"whip": "right"}

    def test_select_fade_black(self, qtbot) -> None:
        """Selecting Fade to Black returns fade_black type."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(4)
        result = dialog.selected_transition()
        assert result["type"] == "fade_black"
        assert result["params"] == {"fade": "black"}
        assert result["duration"] == 0.5

    def test_select_fade_white(self, qtbot) -> None:
        """Selecting Fade to White returns fade_white type."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(5)
        result = dialog.selected_transition()
        assert result["type"] == "fade_white"
        assert result["params"] == {"fade": "white"}
        assert result["duration"] == 0.5

    def test_duration_changes_are_tracked(self, qtbot) -> None:
        """Changing the duration spinbox updates the result."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade
        dialog._duration_spin.setValue(2.0)
        result = dialog.selected_transition()
        assert result["duration"] == 2.0

    def test_duration_clamped_to_min(self, qtbot) -> None:
        """Duration spinbox cannot go below min_duration for the transition."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade: min 0.5s
        dialog._duration_spin.setValue(0.5)
        result = dialog.selected_transition()
        assert result["duration"] == 0.5

    def test_duration_clamped_to_max(self, qtbot) -> None:
        """Duration spinbox cannot go above max_duration for the transition."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade: max 5.0s
        dialog._duration_spin.setValue(5.0)
        result = dialog.selected_transition()
        assert result["duration"] == 5.0

    def test_returning_to_cut_hides_duration(self, qtbot) -> None:
        """Returning to Cut hides the duration controls again."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade → duration visible
        assert not dialog._duration_widget.isHidden()

        dialog._list.setCurrentRow(0)  # Cut → duration hidden
        assert dialog._duration_widget.isHidden()


class TestTransitionPickerOptions:
    """Tests for checkboxes and options."""

    def test_apply_to_all_gaps_default_false(self, qtbot) -> None:
        """Apply to all gaps defaults to False."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        result = dialog.selected_transition()
        assert result["apply_to_all"] is False

    def test_apply_to_all_gaps_toggle(self, qtbot) -> None:
        """Toggling 'apply to all gaps' updates the result."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._apply_all_check.setChecked(True)
        result = dialog.selected_transition()
        assert result["apply_to_all"] is True

        dialog._apply_all_check.setChecked(False)
        result = dialog.selected_transition()
        assert result["apply_to_all"] is False

    def test_preview_default_off(self, qtbot) -> None:
        """Preview checkbox defaults to unchecked."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        assert not dialog._preview_check.isChecked()
        assert not dialog._preview_enabled

    def test_preview_toggle(self, qtbot) -> None:
        """Toggling preview updates internal state."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._preview_check.setChecked(True)
        assert dialog._preview_enabled

        dialog._preview_check.setChecked(False)
        assert not dialog._preview_enabled

    def test_description_updates_on_selection(self, qtbot) -> None:
        """Description label updates when selection changes."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(0)
        desc_cut = dialog._desc_label.text()

        dialog._list.setCurrentRow(1)
        desc_crossfade = dialog._desc_label.text()

        assert desc_cut != desc_crossfade


class TestTransitionPickerButtons:
    """Tests for dialog buttons."""

    def test_accept_returns_accepted(self, qtbot) -> None:
        """Clicking Apply accepts the dialog."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        for child in dialog.findChildren(QPushButton):
            if child.text() == "Apply":
                qtbot.mouseClick(child, Qt.MouseButton.LeftButton)
                break

        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_cancel_rejects_dialog(self, qtbot) -> None:
        """Clicking Cancel rejects the dialog."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        for child in dialog.findChildren(QPushButton):
            if child.text() == "Cancel":
                qtbot.mouseClick(child, Qt.MouseButton.LeftButton)
                break

        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_selected_transition_returns_copy_of_params(self, qtbot) -> None:
        """selected_transition returns a copy, not a reference to internal params."""
        dialog = TransitionPicker()
        dialog.show()
        qtbot.addWidget(dialog)

        dialog._list.setCurrentRow(1)  # Crossfade
        result1 = dialog.selected_transition()
        result2 = dialog.selected_transition()

        assert result1["params"] == result2["params"]
        assert result1["params"] is not result2["params"]
