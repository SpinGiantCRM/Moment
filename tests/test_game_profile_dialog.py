"""Tests for dialogs/game_profile_dialog.py — per-game recording config."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from moment.ui.dialogs.game_profile_dialog import GameProfileDialog

pytestmark = [pytest.mark.gui]


class TestGameProfileDialogInit:
    """Tests for GameProfileDialog construction."""

    def test_create(self, qapp) -> None:

        dlg = GameProfileDialog()
        assert dlg.windowTitle() == "Game Profiles"
        assert dlg.isModal()

    def test_create_with_store(self, qapp) -> None:
        store = MagicMock()
        store.list_game_profiles.return_value = []
        dlg = GameProfileDialog(store=store)
        assert dlg._store is store
        assert dlg._profiles == []

    def test_create_loads_existing_profiles(self, qapp) -> None:
        from moment.core.models import GameProfile

        profile = GameProfile(
            id="gp-1",
            game_name="cs2",
            display_name="Counter-Strike 2",
            replay_duration=45,
            capture_fps=144,
        )
        store = MagicMock()
        store.list_game_profiles.return_value = [profile]

        dlg = GameProfileDialog(store=store)
        assert len(dlg._profiles) == 1
        assert dlg._profiles[0].game_name == "cs2"

    def test_minimum_size(self, qapp) -> None:
        dlg = GameProfileDialog()
        assert dlg.minimumWidth() >= 500
        assert dlg.minimumHeight() >= 400


class TestProfileListOperations:
    """Tests for add/remove profile from the list."""

    def test_add_profile(self, qapp) -> None:
        dlg = GameProfileDialog()
        assert len(dlg._profiles) == 0
        dlg._add_profile()
        assert len(dlg._profiles) == 1
        assert dlg._profiles[0].display_name == "New Game"
        assert dlg._profile_list.count() == 1

    def test_remove_profile(self, qapp) -> None:
        dlg = GameProfileDialog()
        dlg._add_profile()
        assert len(dlg._profiles) == 1
        dlg._profile_list.setCurrentRow(0)
        dlg._remove_profile()
        assert len(dlg._profiles) == 0
        assert dlg._profile_list.count() == 0

    def test_delete_current_profile(self, qapp) -> None:
        store = MagicMock()
        store.list_game_profiles.return_value = []
        dlg = GameProfileDialog(store=store)
        dlg._add_profile()
        dlg._profile_list.setCurrentRow(0)
        dlg._delete_current()
        assert len(dlg._profiles) == 0
        store.delete_game_profile.assert_called_once()

    def test_remove_nothing_when_no_selection(self, qapp) -> None:
        dlg = GameProfileDialog()
        dlg._add_profile()
        assert len(dlg._profiles) == 1
        dlg._profile_list.setCurrentRow(-1)
        dlg._remove_profile()
        assert len(dlg._profiles) == 1  # unchanged


class TestProfileEditing:
    """Tests for editing and saving profiles."""

    def test_select_profile_loads_fields(self, qapp) -> None:
        from moment.core.models import GameProfile

        profile = GameProfile(
            id="gp-1",
            game_name="cs2",
            display_name="Counter-Strike 2",
            replay_duration=30,
            capture_fps=60,
            review_card=None,
        )
        dlg = GameProfileDialog()
        dlg._profiles = [profile]
        dlg._profile_list.addItem("Counter-Strike 2")

        dlg._on_profile_selected(0)
        assert dlg._binary_edit.text() == "cs2"
        assert dlg._display_edit.text() == "Counter-Strike 2"
        assert dlg._replay_sb.value() == 30
        assert dlg._fps_sb.value() == 60

    def test_select_invalid_row_clears_fields(self, qapp) -> None:
        dlg = GameProfileDialog()
        dlg._binary_edit.setText("dirty")
        dlg._on_profile_selected(-1)
        assert dlg._binary_edit.text() == ""

    def test_clear_fields(self, qapp) -> None:
        dlg = GameProfileDialog()
        dlg._binary_edit.setText("foo")
        dlg._display_edit.setText("bar")
        dlg._clear_fields()
        assert dlg._binary_edit.text() == ""

    def test_save_and_close_no_store(self, qapp) -> None:
        dlg = GameProfileDialog(store=None)
        dlg._add_profile()
        dlg._save_and_close()
        assert dlg.result() == 1

    def test_save_and_close_with_store(self, qapp) -> None:
        store = MagicMock()
        store.list_game_profiles.return_value = []
        dlg = GameProfileDialog(store=store)
        dlg._add_profile()
        dlg._profile_list.setCurrentRow(0)
        dlg._binary_edit.setText("cs2")
        dlg._save_and_close()
        store.save_game_profile.assert_called()
        assert dlg.result() == 1

    def test_cancel_does_not_save(self, qapp) -> None:
        store = MagicMock()
        store.list_game_profiles.return_value = []
        dlg = GameProfileDialog(store=store)
        dlg.reject()
        store.save_game_profile.assert_not_called()
        assert dlg.result() == 0


class TestGameProfileWidgets:
    """Tests that all form widgets exist."""

    def test_all_widgets_exist(self, qapp) -> None:
        dlg = GameProfileDialog()
        assert dlg._binary_edit is not None
        assert dlg._display_edit is not None
        assert dlg._replay_sb is not None
        assert dlg._fps_sb is not None
        assert dlg._encode_timing_cb is not None
        assert dlg._quality_slider is not None
        assert dlg._pause_encode_cb is not None
        assert dlg._pause_thumb_cb is not None
        assert dlg._auto_tag_edit is not None
        assert dlg._auto_open_cb is not None
        assert dlg._review_size_cb is not None
        assert dlg._profile_list is not None

    def test_replay_range(self, qapp) -> None:
        dlg = GameProfileDialog()
        assert dlg._replay_sb.minimum() >= 5
        assert dlg._replay_sb.maximum() <= 600

    def test_fps_range(self, qapp) -> None:
        dlg = GameProfileDialog()
        assert dlg._fps_sb.minimum() >= 15
        assert dlg._fps_sb.maximum() <= 240
