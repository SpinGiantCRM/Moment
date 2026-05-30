"""Music panel — background music track for clips.

Lets the user add a background music track (.mp3/.wav/.flac/.m4a),
adjust volume (0-200%), configure fade-in/fade-out durations, and
toggle looping.

Mixed at re-encode via ffmpeg ``amix`` filter.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class MusicPanel(QWidget):
    """Background music track configuration.

    Signals:
        profile_changed: Emitted whenever any music setting changes.
    """

    profile_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # State
        self._music_path = ""
        self._music_volume = 100
        self._fade_in = 0.0
        self._fade_out = 0.0
        self._loop = False

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def music_path(self) -> str:
        return self._music_path

    @property
    def music_volume(self) -> int:
        return self._music_volume

    @property
    def fade_in(self) -> float:
        return self._fade_in

    @property
    def fade_out(self) -> float:
        return self._fade_out

    @property
    def loop(self) -> bool:
        return self._loop

    def set_profile(
        self,
        music_path: str = "",
        music_volume: float = 1.0,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
        loop: bool = False,
    ) -> None:
        """Load state from an existing profile."""
        self._music_path = music_path
        self._music_volume = int(music_volume * 100)
        self._fade_in = fade_in
        self._fade_out = fade_out
        self._loop = loop

        self._path_input.setText(self._music_path)
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(self._music_volume)
        self._volume_slider.blockSignals(False)
        self._fade_in_spin.setValue(self._fade_in)
        self._fade_out_spin.setValue(self._fade_out)
        self._loop_check.setChecked(self._loop)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(16)

        # --- Music file group ---
        file_group = QGroupBox("Background Music")
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(10)

        # File picker row
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Track:"))
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText("No music track selected")
        self._path_input.setReadOnly(True)
        picker_row.addWidget(self._path_input, stretch=1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        picker_row.addWidget(browse_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear)
        picker_row.addWidget(clear_btn)

        file_layout.addLayout(picker_row)

        # Supported formats hint
        hint = QLabel("Supports: .mp3, .wav, .flac, .m4a")
        hint.setObjectName("cardMeta")
        file_layout.addWidget(hint)

        layout.addWidget(file_group)

        # --- Volume group ---
        vol_group = QGroupBox("Volume & Fade")
        vol_layout = QVBoxLayout(vol_group)
        vol_layout.setSpacing(10)

        # Volume slider
        vol_row = QHBoxLayout()
        vol_lbl = QLabel("Volume")
        vol_lbl.setObjectName("cardMeta")
        vol_row.addWidget(vol_lbl)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(100)
        self._volume_slider.valueChanged.connect(self._on_volume)
        vol_row.addWidget(self._volume_slider, stretch=1)

        self._volume_label = QLabel("100%")
        self._volume_label.setObjectName("cardMeta")
        self._volume_label.setFixedWidth(40)
        vol_row.addWidget(self._volume_label)
        vol_layout.addLayout(vol_row)

        # Fade-in
        fade_in_row = QHBoxLayout()
        fade_in_row.addWidget(QLabel("Fade-in"))
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setRange(0.0, 5.0)
        self._fade_in_spin.setSingleStep(0.5)
        self._fade_in_spin.setValue(0.0)
        self._fade_in_spin.valueChanged.connect(self._on_fade_in)
        fade_in_row.addWidget(self._fade_in_spin)
        fade_in_row.addStretch()
        vol_layout.addLayout(fade_in_row)

        # Fade-out
        fade_out_row = QHBoxLayout()
        fade_out_row.addWidget(QLabel("Fade-out"))
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.setRange(0.0, 5.0)
        self._fade_out_spin.setSingleStep(0.5)
        self._fade_out_spin.setValue(0.0)
        self._fade_out_spin.valueChanged.connect(self._on_fade_out)
        fade_out_row.addWidget(self._fade_out_spin)
        fade_out_row.addStretch()
        vol_layout.addLayout(fade_out_row)

        # Loop toggle
        self._loop_check = QCheckBox("Loop track (repeat if shorter than clip)")
        self._loop_check.toggled.connect(self._on_loop)
        vol_layout.addWidget(self._loop_check)

        layout.addWidget(vol_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        """Open a file dialog to select a music track."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Music",
            "",
            "Audio Files (*.mp3 *.wav *.flac *.m4a);;All Files (*)",
        )
        if path:
            self._music_path = path
            self._path_input.setText(path)
            self.profile_changed.emit()

    def _on_clear(self) -> None:
        """Remove the selected music track."""
        self._music_path = ""
        self._path_input.clear()
        self.profile_changed.emit()

    def _on_volume(self, value: int) -> None:
        self._music_volume = value
        self._volume_label.setText(f"{value}%")
        self.profile_changed.emit()

    def _on_fade_in(self, value: float) -> None:
        self._fade_in = value
        self.profile_changed.emit()

    def _on_fade_out(self, value: float) -> None:
        self._fade_out = value
        self.profile_changed.emit()

    def _on_loop(self, checked: bool) -> None:
        self._loop = checked
        self.profile_changed.emit()
