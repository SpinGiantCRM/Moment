"""Search bar — QLineEdit with debounced text change signals.

A 300px wide styled input that fires ``search_changed`` 300 ms after the
last keystroke.  Includes a clear (×) button that appears when text is
present.

Usage::

    bar = SearchBar()
    bar.search_changed.connect(self._on_search)
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLineEdit

from moment.ui.resources import color

_DEBOUNCE_MS = 300
_SEARCH_WIDTH = 300


class SearchBar(QLineEdit):
    """A debounced search input with a clear button."""

    search_changed = pyqtSignal(str)

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Filter clips…")
        self.setFixedWidth(_SEARCH_WIDTH)
        self.setClearButtonEnabled(True)
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: {color("--bg-inset")};
                color: {color("--text-primary")};
                border: 1px solid {color("--border-menu")};
                border-radius: 4px;
                padding: 5px 32px 5px 8px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {color("--accent-blue")};
            }}
        """)

        # Debounce timer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_search)

        # Re-connect: textChanged → restart debounce
        self.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """Restart the debounce timer on every keystroke."""
        self._debounce.start()

    def _emit_search(self) -> None:
        """Fire the debounced signal."""
        self.search_changed.emit(self.text())

    def clear_search(self) -> None:
        """Reset the search field from outside."""
        self.clear()
