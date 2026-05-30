"""Tests for context_menu.py — right-click clip context menu builder."""

from __future__ import annotations

from moment.core.models import Clip, ClipStatus, ClipType, ClipVisibility
from moment.ui.widgets.context_menu import ContextMenuBuilder


def _make_clip(**kwargs) -> Clip:
    """Create a minimal Clip for testing."""
    defaults = {
        "id": "test-id",
        "stem": "test",
        "source_path": __import__("pathlib").Path("/tmp/test.mkv"),
        "duration": 30.0,
        "status": ClipStatus.DONE,
        "visibility": ClipVisibility.PRIVATE,
        "clip_type": ClipType.VIDEO,
    }
    defaults.update(kwargs)
    return Clip(**defaults)


class TestContextMenuBuilderInit:
    """Tests for ContextMenuBuilder construction."""

    def test_create(self, qapp) -> None:
        """ContextMenuBuilder can be created with a Clip."""
        clip = _make_clip()
        builder = ContextMenuBuilder(clip)
        assert builder._clip == clip

    def test_signals_exist(self, qapp) -> None:
        """All expected signals are defined (checked on class, not instance)."""
        # pyqtSignal descriptors raise TypeError on non-QObject instances,
        # so check on the class instead.
        signal_names = [
            "copy_url_triggered", "rename_triggered", "open_source_triggered",
            "open_encoded_triggered", "open_player_triggered",
            "reencode_triggered", "reupload_triggered",
            "favorite_triggered", "manage_tags_triggered",
            "set_game_triggered", "protect_triggered",
            "delete_triggered", "select_triggered",
        ]
        for name in signal_names:
            assert hasattr(ContextMenuBuilder, name), f"Missing signal: {name}"


class TestContextMenuBuilderBuild:
    """Tests for build() method."""

    def test_build_returns_menu(self, qapp) -> None:
        """build() returns a QMenu."""
        clip = _make_clip()
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        assert menu is not None

    def test_menu_has_actions(self, qapp) -> None:
        """Menu contains multiple actions."""
        clip = _make_clip()
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        assert len(menu.actions()) > 10

    def test_encoded_action_disabled_when_no_path(self, qapp) -> None:
        """'Open Encoded Folder' is disabled when clip has no encoded_path."""
        clip = _make_clip(encoded_path=None)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        for action in menu.actions():
            if action and "Encoded" in (action.text() or ""):
                assert not action.isEnabled()

    def test_encoded_action_enabled_when_has_path(self, qapp) -> None:
        """'Open Encoded Folder' is enabled when clip has encoded_path."""
        clip = _make_clip(encoded_path=__import__("pathlib").Path("/tmp/enc.mkv"))
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        for action in menu.actions():
            if action and "Encoded" in (action.text() or ""):
                assert action.isEnabled()

    def test_reupload_disabled_when_no_r2_url(self, qapp) -> None:
        """'Re-upload' is disabled when clip has no r2_url."""
        clip = _make_clip(r2_url=None)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        for action in menu.actions():
            if action and "upload" in (action.text() or "").lower():
                assert not action.isEnabled()

    def test_reupload_enabled_when_has_r2_url(self, qapp) -> None:
        """'Re-upload' is enabled when clip has r2_url."""
        clip = _make_clip(r2_url="https://example.com/clip.mp4")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        for action in menu.actions():
            if action and "upload" in (action.text() or "").lower():
                assert action.isEnabled()

    def test_favorite_text_for_non_favorite(self, qapp) -> None:
        """Non-favorite clip shows '☆ Toggle Favorite'."""
        clip = _make_clip(favorite=False)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        found = False
        for action in menu.actions():
            if action and "Favorite" in (action.text() or ""):
                assert "☆" in action.text()
                found = True
        assert found

    def test_favorite_text_for_favorite(self, qapp) -> None:
        """Favorite clip shows '★ Unfavorite'."""
        clip = _make_clip(favorite=True)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        found = False
        for action in menu.actions():
            if action and (
                "Unfavorite" in (action.text() or "")
                or "Favorite" in (action.text() or "")
            ):
                assert "★" in action.text() or "Unfavorite" in action.text()
                found = True
        assert found

    def test_protect_text_for_non_protected(self, qapp) -> None:
        """Non-protected clip shows 'Protect from Retention'."""
        clip = _make_clip(protect_from_retention=False)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        found = False
        for action in menu.actions():
            if action and "Protect" in (action.text() or "") and "🔒" not in (action.text() or ""):
                assert "Protect from Retention" in action.text()
                found = True
        assert found

    def test_protect_text_for_protected(self, qapp) -> None:
        """Protected clip shows '🔒 Unprotect'."""
        clip = _make_clip(protect_from_retention=True)
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        for action in menu.actions():
            if action and "Unprotect" in (action.text() or ""):
                assert "🔒" in action.text()


class TestContextMenuBuilderSignals:
    """Tests for actions exist and are wired to the correct clip_id.

    ContextMenuBuilder is a plain class (not QObject), so signals cannot
    be connected on instances.  Instead we verify the QMenu actions carry
    the expected text and are present."""

    def test_copy_url_action_present(self, qapp) -> None:
        """Copy URL action exists in menu."""
        clip = _make_clip(id="signal-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any("Copy URL" in t for t in texts)

    def test_rename_action_present(self, qapp) -> None:
        """Rename action exists in menu."""
        clip = _make_clip(id="rename-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any("Rename" in t for t in texts)

    def test_delete_action_present(self, qapp) -> None:
        """Delete action exists in menu."""
        clip = _make_clip(id="del-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any("Delete" in t for t in texts)

    def test_select_action_present(self, qapp) -> None:
        """Select action exists in menu."""
        clip = _make_clip(id="sel-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any(t == "Select" for t in texts)

    def test_favorite_action_present(self, qapp) -> None:
        """Favorite/Unfavorite action exists in menu."""
        clip = _make_clip(id="fav-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any("Favorite" in t or "Unfavorite" in t for t in texts)

    def test_reencode_action_present(self, qapp) -> None:
        """Re-encode action exists in menu."""
        clip = _make_clip(id="reenc-test")
        builder = ContextMenuBuilder(clip)
        menu = builder.build()
        texts = [a.text() for a in menu.actions() if a]
        assert any("encode" in t.lower() for t in texts)
