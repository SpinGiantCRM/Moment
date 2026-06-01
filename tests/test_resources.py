"""Tests for ui/resources.py — QSS stylesheet, colour tokens, icon loading."""

from __future__ import annotations
import pytest

from moment.ui.resources import (
    app_font,
    color,
    icon_pixmap,
    load_icon,
    qss_colors,
    set_font,
    apply_spacing,
    stylesheet,
)
pytestmark = [pytest.mark.gui]


class TestColorTokens:
    """Tests for colour token resolution."""

    def test_known_token_returns_hex(self) -> None:
        assert color("--bg-window") == "#1a1a1a"

    def test_unknown_token_returns_fallback(self) -> None:
        assert color("--nonexistent") == "#000000"

    def test_accent_tokens_exist(self) -> None:
        for token in ("--accent-blue", "--accent-green", "--accent-orange", "--accent-red"):
            assert color(token).startswith("#")

    def test_all_tokens_are_strings(self) -> None:
        result = color("--bg-surface")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_new_palette_tokens(self) -> None:
        """Verify key new palette tokens exist with correct values."""
        assert color("--accent-blue") == "#4a9eff"
        assert color("--accent-green") == "#34d399"
        assert color("--accent-red") == "#f87171"
        assert color("--btn-primary-bg") == "#4a9eff"
        assert color("--heart-active") == "#f87171"
        assert color("--border-input") == "#444444"
        assert color("--toggle-active") == "#4a9eff"


class TestQssColors:
    """Tests for the QSS :root colour variable declaration."""

    def test_returns_string(self) -> None:
        result = qss_colors()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_tokens(self) -> None:
        result = qss_colors()
        assert "--bg-window" in result
        assert "--text-primary" in result
        assert "--accent-blue" in result

    def test_contains_hex_values(self) -> None:
        result = qss_colors()
        assert "#1a1a1a" in result
        assert "#4a9eff" in result


class TestStylesheet:
    """Tests for the full application stylesheet."""

    def test_returns_string(self) -> None:
        result = stylesheet()
        assert isinstance(result, str)
        assert len(result) > 1000

    def test_cached_return_same_object(self) -> None:
        s1 = stylesheet()
        s2 = stylesheet()
        assert s1 is s2

    def test_contains_widget_rules(self) -> None:
        result = stylesheet()
        assert "QMainWindow" in result
        assert "QPushButton#primary" in result
        assert "QPushButton#secondary" in result
        assert "QPushButton#danger" in result
        assert "QListView" in result
        assert "QScrollBar" in result
        assert "QComboBox" in result
        assert "QCheckBox" in result
        assert "QToolButton#sidebarBtn" in result
        assert "QPushButton#toolbarAction" in result
        assert "QToolButton#cardSizeToggle" in result

    def test_contains_font_stack(self) -> None:
        result = stylesheet()
        assert "Open Sans" in result


class TestAppFont:
    """Tests for app font creation."""

    def test_default_size(self) -> None:
        font = app_font()
        assert font.pointSize() == 10

    def test_custom_size(self) -> None:
        font = app_font(size=13)
        assert font.pointSize() == 13

    def test_family_list_non_empty(self) -> None:
        font = app_font()
        families = font.families()
        assert len(families) > 0
        assert "Open Sans" in families


class TestSetFont:
    """Tests for typography helper."""

    def test_set_font_known_token(self, qapp) -> None:
        from PyQt6.QtWidgets import QLabel
        label = QLabel("Test")
        set_font(label, "title")
        font = label.font()
        assert font.pointSize() == 18
        assert font.weight() == 600

    def test_set_font_unknown_token(self, qapp) -> None:
        from PyQt6.QtWidgets import QLabel
        label = QLabel("Test")
        # Should not raise, just log warning
        set_font(label, "nonexistent_token")


class TestSpacing:
    """Tests for spacing helpers."""

    def test_apply_spacing_default(self) -> None:
        assert apply_spacing("space-4") == 12

    def test_apply_spacing_compact(self) -> None:
        assert apply_spacing("space-4", "compact") == 10  # 12 * 0.85

    def test_apply_spacing_comfortable(self) -> None:
        assert apply_spacing("space-4", "comfortable") == 14  # 12 * 1.15

    def test_apply_spacing_unknown_token(self) -> None:
        assert apply_spacing("space-nonexistent") == 8  # default fallback


class TestIconLoading:
    """Tests for SVG icon loading."""

    def test_moment_icon_loads(self, qapp) -> None:
        icon = load_icon("moment")
        assert not icon.isNull()

    def test_cached_icon_returns_same(self, qapp) -> None:
        icon1 = load_icon("moment", size=24)
        icon2 = load_icon("moment", size=24)
        assert icon1 is icon2

    def test_different_size_different_cache_key(self, qapp) -> None:
        icon_small = load_icon("moment", size=16)
        icon_large = load_icon("moment", size=24)
        assert not icon_small.isNull()
        assert not icon_large.isNull()

    def test_nonexistent_icon_returns_null(self, qapp) -> None:
        icon = load_icon("nonexistent_icon_xyz", size=24)
        assert icon.isNull()

    def test_icon_pixmap_alias(self, qapp) -> None:
        icon = icon_pixmap("moment")
        assert not icon.isNull()

    def test_colored_icon_loads(self, qapp) -> None:
        """load_icon('library', '#a0a0a0') returns a valid QIcon."""
        icon = load_icon("library", "#a0a0a0")
        assert not icon.isNull()
        # Verify it renders to a non-empty pixmap
        pixmap = icon.pixmap(24, 24)
        assert not pixmap.isNull()
        assert pixmap.width() == 24
        assert pixmap.height() == 24

    def test_colored_icon_cached_separately(self, qapp) -> None:
        """Different colours produce different cache entries."""
        icon_grey = load_icon("library", "#a0a0a0", size=24)
        icon_blue = load_icon("library", "#4a9eff", size=24)
        assert not icon_grey.isNull()
        assert not icon_blue.isNull()
        # They should be different objects (different cache keys)
        assert icon_grey is not icon_blue

    def test_null_color_loads_as_qicon_from_path(self, qapp) -> None:
        """When color is None, the icon loads via QIcon(path)."""
        icon = load_icon("library", color=None, size=24)
        assert not icon.isNull()

    def test_all_icons_load(self, qapp) -> None:
        """Smoke-test: every SVG in assets/icons/ loads without error."""
        from pathlib import Path
        icons_dir = Path(__file__).resolve().parent.parent / "src" / "moment" / "ui" / "assets" / "icons"
        svg_files = sorted(icons_dir.glob("*.svg"))
        for svg_path in svg_files:
            name = svg_path.stem
            icon = load_icon(name, "#a0a0a0")
            assert not icon.isNull(), f"Failed to load coloured icon: {name}"
            # Also test uncoloured path
            icon2 = load_icon(name)
            assert not icon2.isNull(), f"Failed to load icon: {name}"
