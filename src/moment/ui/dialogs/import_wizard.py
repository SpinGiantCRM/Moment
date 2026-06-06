"""First-run import wizard — detect recordings, configure paths, and import."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from moment.core.config import _PATH_DEFAULTS
from moment.core.import_discovery import (
    RecordingCandidate,
    discover_recording_paths,
    ensure_recording_dirs,
    import_recordings_from_dirs,
)

if TYPE_CHECKING:
    from moment.core.config import Config
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class ImportWizardDialog(QDialog):
    """Guide the user through recording discovery, path setup, and import.

    Case A — recordings found: checkbox list of candidates + encode path.
    Case B — nothing found: manual source/encode folder selection.
    """

    def __init__(
        self,
        config: "Config",
        store: "Store",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store
        self._candidates: list[RecordingCandidate] = discover_recording_paths(config, store)
        self._imported_count = 0
        self._imported_from = ""

        self.setWindowTitle("Import Recordings")
        self.setMinimumWidth(520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        if self._candidates:
            self._build_found_ui(root)
        else:
            self._build_not_found_ui(root)

        button_row = QHBoxLayout()
        button_row.addStretch()
        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(self._on_skip)
        button_row.addWidget(skip_btn)

        if self._candidates:
            action_btn = QPushButton("Configure && Import")
            action_btn.setObjectName("primary")
            action_btn.clicked.connect(self._on_configure_and_import)
        else:
            action_btn = QPushButton("Save && Continue")
            action_btn.setObjectName("primary")
            action_btn.clicked.connect(self._on_save_and_continue)
        button_row.addWidget(action_btn)
        root.addLayout(button_row)

    @property
    def imported_count(self) -> int:
        """Number of clips imported during this session."""
        return self._imported_count

    @property
    def imported_from(self) -> str:
        """Human-readable summary of import source(s)."""
        return self._imported_from

    def _build_found_ui(self, root: QVBoxLayout) -> None:
        heading = QLabel("Recordings Found")
        heading.setObjectName("dialogHeading")
        root.addWidget(heading)

        desc = QLabel("I found clips in these locations:")
        desc.setWordWrap(True)
        root.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)

        self._candidate_checks: list[tuple[QCheckBox, RecordingCandidate]] = []
        for candidate in self._candidates:
            display = self._short_path(candidate["source_dir"])
            new_count = candidate["clip_count_new"]
            total = candidate["clip_count"]
            if new_count < total:
                count_text = f"{new_count} new ({total} total)"
            else:
                count_text = f"{total} clip{'s' if total != 1 else ''}"
            cb = QCheckBox(f"{display}  ({count_text})")
            cb.setChecked(new_count > 0)
            cb.setEnabled(new_count > 0)
            if new_count == 0:
                cb.setToolTip("All clips from this folder are already in the library")
            scroll_layout.addWidget(cb)
            self._candidate_checks.append((cb, candidate))
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        root.addWidget(scroll)

        encode_row = QHBoxLayout()
        encode_row.addWidget(QLabel("Encode output:"))
        self._encode_edit = QLineEdit(self._default_encode_dir())
        encode_row.addWidget(self._encode_edit, stretch=1)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_encode_dir)
        encode_row.addWidget(browse)
        root.addLayout(encode_row)

    def _build_not_found_ui(self, root: QVBoxLayout) -> None:
        heading = QLabel("No Recordings Found")
        heading.setObjectName("dialogHeading")
        root.addWidget(heading)

        desc = QLabel(
            "I didn't find any existing recordings.\n\n"
            "Choose where gpu-screen-recorder saves recordings and where "
            "encoded clips should be stored."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addWidget(QLabel("Source folder (recordings):"))
        source_row = QHBoxLayout()
        self._source_edit = QLineEdit(self._default_recordings_dir())
        source_row.addWidget(self._source_edit, stretch=1)
        source_browse = QPushButton("Browse")
        source_browse.clicked.connect(self._browse_source_dir)
        source_row.addWidget(source_browse)
        root.addLayout(source_row)

        create_source = QPushButton("Create Folder")
        create_source.clicked.connect(self._create_source_dir)
        root.addWidget(create_source)

        root.addWidget(QLabel("Encoded output:"))
        encode_row = QHBoxLayout()
        self._encode_edit = QLineEdit(self._default_encode_dir())
        encode_row.addWidget(self._encode_edit, stretch=1)
        encode_browse = QPushButton("Browse")
        encode_browse.clicked.connect(self._browse_encode_dir)
        encode_row.addWidget(encode_browse)
        root.addLayout(encode_row)

        create_encode = QPushButton("Create Folder")
        create_encode.clicked.connect(self._create_encode_dir)
        root.addWidget(create_encode)

    def _default_recordings_dir(self) -> str:
        return self._config.get_path("recordings_dir") or _PATH_DEFAULTS["recordings_dir"]

    def _default_encode_dir(self) -> str:
        return self._config.get_path("encode_dir") or _PATH_DEFAULTS["encode_dir"]

    @staticmethod
    def _short_path(path: str) -> str:
        return os.path.expanduser(path).replace(os.path.expanduser("~"), "~")

    def _browse_source_dir(self) -> None:
        current = self._source_edit.text() or self._default_recordings_dir()
        directory = QFileDialog.getExistingDirectory(self, "Select source folder", current)
        if directory:
            self._source_edit.setText(directory)

    def _browse_encode_dir(self) -> None:
        current = self._encode_edit.text() or self._default_encode_dir()
        directory = QFileDialog.getExistingDirectory(self, "Select encode output folder", current)
        if directory:
            self._encode_edit.setText(directory)

    def _create_source_dir(self) -> None:
        path = self._source_edit.text().strip() or self._default_recordings_dir()
        encode = self._encode_edit.text().strip() or self._default_encode_dir()
        created = ensure_recording_dirs(path, encode)[0]
        self._source_edit.setText(str(created))

    def _create_encode_dir(self) -> None:
        source = self._source_edit.text().strip() or self._default_recordings_dir()
        path = self._encode_edit.text().strip() or self._default_encode_dir()
        created = ensure_recording_dirs(source, path)[1]
        self._encode_edit.setText(str(created))

    def _save_paths(self, source_dir: str, encode_dir: str) -> None:
        self._config.set_path("recordings_dir", source_dir)
        self._config.set_path("encode_dir", encode_dir)

    def _on_skip(self) -> None:
        self._config.set("setup_wizard_seen", True)
        self.reject()

    def _on_configure_and_import(self) -> None:
        selected = [c for cb, c in self._candidate_checks if cb.isChecked()]
        if not selected:
            QMessageBox.warning(
                self,
                "No folders selected",
                "Select at least one folder to import.",
            )
            return

        encode_dir = self._encode_edit.text().strip() or self._default_encode_dir()
        source_dir = selected[0]["source_dir"]
        self._save_paths(source_dir, encode_dir)

        source_dirs = [c["source_dir"] for c in selected]
        self._imported_count = import_recordings_from_dirs(self._store, source_dirs)
        self._imported_from = ", ".join(self._short_path(s) for s in source_dirs)

        self._config.set("setup_wizard_seen", True)
        self.accept()

    def _on_save_and_continue(self) -> None:
        source_dir = self._source_edit.text().strip()
        encode_dir = self._encode_edit.text().strip()
        if not source_dir:
            QMessageBox.warning(self, "Source folder required", "Enter a source folder path.")
            return
        if not encode_dir:
            QMessageBox.warning(self, "Encode folder required", "Enter an encode output path.")
            return

        ensure_recording_dirs(source_dir, encode_dir)
        try:
            self._save_paths(source_dir, encode_dir)
        except Exception as exc:
            logger.exception("Failed to save import wizard paths: %s", exc)
            QMessageBox.critical(self, "Save failed", f"Could not save paths:\n{exc}")
            return

        self._imported_count = import_recordings_from_dirs(self._store, [source_dir])
        if self._imported_count:
            self._imported_from = self._short_path(source_dir)
        else:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "info",
                "No clips found",
                "Paths saved — no video files to import.",
            )

        self._config.set("setup_wizard_seen", True)
        self.accept()
