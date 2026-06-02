"""Editor window — dedicated QMainWindow for complex clip edits.

Hosts a tabbed interface with Timeline, Filters, Merge, and Music panels.
Auto-saves an :class:`EditProfile` to the store on every change.

Usage::

    window = EditorWindow(clip_id="abc", store=store)
    window.show()
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from moment.core.models import EditProfile
from moment.ui.editor.filter_panel import FilterPanel
from moment.ui.editor.gif_exporter import GifExporter
from moment.ui.editor.merge_panel import MergePanel
from moment.ui.editor.music_panel import MusicPanel
from moment.ui.editor.timeline_panel import TimelinePanel
from moment.ui.resources import color

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

_AUTOSAVE_MS = 2000  # debounce auto-save by 2s


class EditorWindow(QMainWindow):
    """Dedicated editor window for a single clip.

    Signals:
        profile_saved: Emitted when an EditProfile is auto-saved to the store.
        close_requested: Emitted when the user closes the editor.
    """

    profile_saved = pyqtSignal(str)  # clip_id
    close_requested = pyqtSignal()

    def __init__(
        self,
        clip_id: str,
        store: "Store",
        clip_duration: float = 0.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._clip_id = clip_id
        self._store = store
        self._clip_duration = max(clip_duration, 0.1)

        # Load or create the edit profile
        self._profile = store.get_edit_profile(clip_id)
        if self._profile is None:
            self._profile = EditProfile(clip_id=clip_id)

        # Undo stack for Ctrl+Z support
        self._undo_stack: list[EditProfile] = []

        # Track unsaved changes for close prompt
        self._dirty = False

        # Auto-save timer (debounced)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._do_save)

        self._build_ui()
        self._connect_signals()
        self._load_profile_into_panels()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the editor window layout."""
        self.setWindowTitle("Moment — Editor")
        self.setMinimumSize(900, 650)
        self.setStyleSheet(f"background-color: {color('--bg-window')};")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        # --- Header ---
        header = QHBoxLayout()
        title = QLabel("Editor")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()

        gif_btn = QPushButton("GIF Export…")
        gif_btn.clicked.connect(self._open_gif_export)
        header.addWidget(gif_btn)

        done_btn = QPushButton("Done")
        done_btn.setObjectName("accent")
        done_btn.clicked.connect(self.close)
        header.addWidget(done_btn)

        layout.addLayout(header)

        # --- Tab widget ---
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{
                background-color: {color("--bg-window")};
                border: 1px solid {color("--border-menu")};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                padding: 8px 20px;
                background: transparent;
                color: {color("--text-secondary")};
                border: none;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                color: {color("--text-primary")};
                border-bottom: 2px solid {color("--accent-blue")};
            }}
            """
        )

        # --- Timeline tab ---
        self._timeline = TimelinePanel(self._clip_duration)
        self._tabs.addTab(self._timeline, "Timeline")

        # --- Filters tab ---
        self._filters = FilterPanel()
        self._tabs.addTab(self._filters, "Filters")

        # --- Merge tab ---
        self._merge = MergePanel(self._store)
        self._tabs.addTab(self._merge, "Merge")

        # --- Music tab ---
        self._music = MusicPanel()
        self._tabs.addTab(self._music, "Music")

        layout.addWidget(self._tabs, stretch=1)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Wire panel change signals to auto-save."""
        self._timeline.profile_changed.connect(self._schedule_save)
        self._filters.profile_changed.connect(self._schedule_save)
        self._merge.profile_changed.connect(self._schedule_save)
        self._music.profile_changed.connect(self._schedule_save)

    # ------------------------------------------------------------------
    # Profile load
    # ------------------------------------------------------------------

    def _load_profile_into_panels(self) -> None:
        """Push the current EditProfile state into all panels."""
        p = self._profile
        self._timeline.set_profile(
            trim_start=p.trim_start,
            trim_end=p.trim_end,
            split_points=p.split_points,
            segments=p.segments,
        )
        self._filters.set_profile(
            filters=p.filters,
            overlays=p.overlays,
        )
        if p.merge_source_ids:
            for cid in p.merge_source_ids:
                self._merge.add_clip(cid)

        self._music.set_profile(
            music_path="",
            music_volume=1.0,
            fade_in=0.0,
            fade_out=0.0,
            loop=False,
        )

    # ------------------------------------------------------------------
    # Auto-save
    # ------------------------------------------------------------------

    def _schedule_save(self) -> None:
        """Debounced save — collects state from panels into the profile."""
        self._dirty = True
        self._save_timer.start()

    def _do_save(self) -> None:
        """Gather state from all panels and persist to the store."""
        try:
            # Snapshot for undo before mutating
            self._undo_stack.append(copy.deepcopy(self._profile))
            if len(self._undo_stack) > 20:
                self._undo_stack.pop(0)

            p = self._profile

            # Timeline
            p.trim_start = self._timeline.trim_start
            p.trim_end = self._timeline.trim_end
            p.split_points = self._timeline.split_points
            p.segments = self._timeline.segments

            # Filters
            p.filters = self._filters.filters
            p.overlays = self._filters.overlays

            # Increment version
            p.edit_version += 1

            self._store.save_edit_profile(p)
            self._dirty = False
            self.profile_saved.emit(self._clip_id)
            logger.debug("EditProfile saved (v%d) for %s", p.edit_version, self._clip_id)
        except Exception as exc:
            logger.exception("Failed to save EditProfile: %s", exc)

    # ------------------------------------------------------------------
    # GIF export
    # ------------------------------------------------------------------

    def _open_gif_export(self) -> None:
        """Open the GIF export dialog."""
        dialog = GifExporter(self._clip_id, self._clip_duration, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Flush pending save with prompt if dirty, then emit close_requested."""
        if self._dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved edits. Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_timer.stop()
                self._do_save()
            elif reply == QMessageBox.StandardButton.Discard:
                self._save_timer.stop()
                self._dirty = False
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        self._save_timer.stop()
        self.close_requested.emit()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Handle keyboard shortcuts for the editor.

        Shortcuts:
            Ctrl+Z       — Undo last save
            Ctrl+S       — Save current edits
            Escape       — Close editor (prompt if unsaved)
            Space        — Play/Pause (no-op with guidance)
            Ctrl+Shift+E — Open GIF export dialog
        """
        mods = event.modifiers()
        key = event.key()

        if mods == Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                self._undo()
                return
            if key == Qt.Key.Key_S:
                self._save_timer.stop()
                self._do_save()
                return

        if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if key == Qt.Key.Key_E:
                self._open_gif_export()
                return

        if key == Qt.Key.Key_Escape:
            self.close()
            return

        if key == Qt.Key.Key_Space and mods == Qt.KeyboardModifier.NoModifier:
            # No video player in editor — informational
            logger.debug("Space pressed — no preview player in editor")
            return

        super().keyPressEvent(event)

    def _undo(self) -> None:
        """Restore the last saved profile state."""
        if not self._undo_stack:
            logger.debug("Undo stack empty — nothing to undo")
            return

        prev = self._undo_stack.pop()
        self._profile = prev
        self._load_profile_into_panels()
        self._dirty = False
        self._store.save_edit_profile(prev)
        self.profile_saved.emit(self._clip_id)
        logger.debug("Undo: restored profile v%d", prev.edit_version)
