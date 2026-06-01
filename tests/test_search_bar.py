"""Tests for search_bar.py — debounced search input."""

from __future__ import annotations
import pytest
pytestmark = [pytest.mark.gui]


class TestSearchBarInit:
    """Tests for SearchBar construction and defaults."""

    def test_create(self, qtbot) -> None:

        """SearchBar can be created."""
        from moment.ui.widgets.search_bar import _SEARCH_WIDTH, SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        assert bar.width() == _SEARCH_WIDTH
        assert bar.placeholderText() == "Filter clips…"

    def test_clear_button_enabled(self, qtbot) -> None:
        """Clear button is enabled by default."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        assert bar.isClearButtonEnabled()

    def test_debounce_timer_is_single_shot(self, qtbot) -> None:
        """Debounce timer is single-shot."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        assert bar._debounce.isSingleShot()
        assert bar._debounce.interval() == 300

    def test_text_empty_by_default(self, qtbot) -> None:
        """Text is empty by default."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        assert bar.text() == ""

class TestSearchBarSignal:
    """Tests for search_changed signal."""

    def test_text_change_starts_debounce(self, qtbot) -> None:
        """Typing text starts the debounce timer."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        bar.setText("test")
        assert bar._debounce.isActive()

    def test_debounce_emits_search_changed(self, qtbot) -> None:
        """After debounce timeout, search_changed is emitted."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        bar.setText("hello")

        with qtbot.waitSignal(bar.search_changed, timeout=1000) as blocker:
            # Fast-forward the debounce timer
            bar._debounce.stop()
            bar._emit_search()

        assert blocker.args == ["hello"]

    def test_multiple_keystrokes_restart_debounce(self, qtbot) -> None:
        """Multiple rapid keystrokes restart the debounce timer."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        bar.setText("a")
        assert bar._debounce.isActive()
        bar.setText("ab")
        assert bar._debounce.isActive()

    def test_empty_text_emitted(self, qtbot) -> None:
        """Empty text is emitted on search_changed."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        bar.setText("something")
        bar.clear()

        with qtbot.waitSignal(bar.search_changed, timeout=1000) as blocker:
            bar._debounce.stop()
            bar._emit_search()

        assert blocker.args == [""]

class TestSearchBarClear:
    """Tests for clear_search()."""

    def test_clear_search_clears_text(self, qtbot) -> None:
        """clear_search() resets the text field."""
        from moment.ui.widgets.search_bar import SearchBar

        bar = SearchBar()
        qtbot.addWidget(bar)
        bar.setText("find me")
        assert bar.text() == "find me"
        bar.clear_search()
        assert bar.text() == ""


