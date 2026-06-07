"""Themed dialog base class — ensures child dialogs use Moment's dark QSS."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QDialog, QWidget

from moment.ui.resources import stylesheet


class ThemedDialog(QDialog):
    """QDialog that applies Moment's stylesheet and styled background.

    Child dialogs on Linux otherwise inherit the platform (Breeze) palette
    instead of the application theme.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(stylesheet())

    def showEvent(self, event: QShowEvent) -> None:
        """Re-apply stylesheet on show to override KDE titlebar palette bleed."""
        super().showEvent(event)
        self.setStyleSheet(stylesheet())
