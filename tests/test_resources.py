"""Tests for ui/resources.py — QSS stylesheet, colour tokens, icon loading."""

from __future__ import annotations
import pytest

from moment.ui.resources import (
    app_font,
    color,
    icon_pixmap,
    load_icon,
    qss_colors,
    stylesheet,
)
pytestmark = [pytest.mark.gui]


class TestColorTokens:
    """Tests for colour token resolution."""

    def test_known_token_returns_hex(self) -> None:

        assert color("--bg-window") == "#3c3c3c"

    def test_unknown_token_returns_fallback(self) -> None:
        assert color("--nonexistent") == "#000000"

    def test_accent_tokens_exist(self) -> None:
        for token in ("--accent-blue", "--accent-green", "--accent-orange", "--accent-red"):
            assert color(token).startswith("#")

    def test_all_tokens_are_strings(self) -> None:
        result = color("--bg-surface")
        assert isinstance(result, str)
        assert len(result) > 0

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
        assert "#3c3c3c" in result
        assert "#60a5fa" in result

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
        assert "QPushButton" in result
        assert "QListView" in result
        assert "QScrollBar" in result
        assert "QComboBox" in result
        assert "QCheckBox" in result

    def test_contains_font_stack(self) -> None:
        result = stylesheet()
        assert "Noto Sans" in result

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
        assert "Noto Sans" in families

class TestIconLoading:
    """Tests for SVG icon loading."""

    def test_moment_icon_loads(self) -> None:
        icon = load_icon("moment")
        assert not icon.isNull()

    def test_cached_icon_returns_same(self) -> None:
        icon1 = load_icon("moment", size=24)
        icon2 = load_icon("moment", size=24)
        assert icon1 is icon2

    def test_different_size_different_cache_key(self) -> None:
        icon_small = load_icon("moment", size=16)
        icon_large = load_icon("moment", size=24)
        # Different cache entries but both valid
        assert not icon_small.isNull()
        assert not icon_large.isNull()

    def test_nonexistent_icon_returns_null(self) -> None:
        icon = load_icon("nonexistent_icon_xyz", size=24)
        assert icon.isNull()

    def test_icon_pixmap_alias(self) -> None:
        icon = icon_pixmap("moment")
        assert not icon.isNull()


