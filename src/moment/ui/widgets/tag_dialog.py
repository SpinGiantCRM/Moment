"""Tag dialog — simple modal for editing clip tags.

Presents a text field pre-populated with existing tags and returns
the updated tag list on accept.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class TagDialog(QDialog):
    """Modal dialog for editing comma-separated tags on a clip.

    Usage::

        dlg = TagDialog(["existing", "tags"], parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tags = dlg.tags()
    """

    def __init__(
        self,
        current_tags: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Tags")
        self.setMinimumWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Instruction label
        label = QLabel("Enter tags separated by commas:")
        label.setWordWrap(True)
        layout.addWidget(label)

        # Tag input
        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g. clutch, funny, 360-noscope")
        if current_tags:
            self._input.setText(", ".join(current_tags))
            self._input.selectAll()
        layout.addWidget(self._input)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def tags(self) -> list[str]:
        """Return the parsed tag list from user input.

        Empty strings and whitespace-only entries are stripped.
        """
        raw = self._input.text().strip()
        if not raw:
            return []
        return [
            t.strip()
            for t in raw.split(",")
            if t.strip()
        ]
