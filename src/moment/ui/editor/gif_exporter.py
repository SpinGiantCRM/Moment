"""GIF exporter — dialog for exporting clips as animated GIFs.

Uses ffmpeg ``palettegen`` + ``paletteuse`` for high-quality GIF output.
Runs encoding in a background thread and shows a progress bar.

Usage::

    dialog = GifExporter(clip_id="abc", duration=30.0, parent=self)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        print("GIF saved to:", dialog.output_path())
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 — required for TimeoutExpired, CalledProcessError
import threading
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color
from moment.utils.subprocess import ExternalCommandRunner

logger = logging.getLogger(__name__)

_RESOLUTION_PRESETS = {
    "320p": (320, 180),
    "480p": (480, 270),
    "720p": (720, 405),
    "1080p": (1080, 608),
}

_FPS_OPTIONS = ["10", "15", "20", "24", "30"]


class GifExporter(QDialog):
    """Modal dialog for exporting a clip as an animated GIF.

    Signals:
        export_finished(str): Emitted with the output path on success.
        export_error(str): Emitted with an error message on failure.
    """

    export_finished = pyqtSignal(str)
    export_error = pyqtSignal(str)

    # Signal for progress updates from background thread
    _progress_updated = pyqtSignal(int)

    def __init__(
        self,
        clip_id: str,
        duration: float = 0.0,
        source_path: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._clip_id = clip_id
        self._duration = max(duration, 0.1)
        self._source_path = source_path
        self._output_path = str(Path.home() / "Pictures" / "Moment" / f"{clip_id}.gif")

        # Settings
        self._resolution = "480p"
        self._fps = 15
        self._start = 0.0
        self._end = duration

        # Background thread control
        self._running = False
        self._proc = None  # ExternalCommandRunner handles PID tracking

        self.setWindowTitle("Export GIF")
        self.setMinimumWidth(450)
        self.setStyleSheet(f"background-color: {color('--bg-window')};")
        self.setModal(True)

        self._build_ui()

        # Wire signals for thread-safe UI updates
        self._progress_updated.connect(self._progress.setValue)
        self.export_finished.connect(self._on_export_done)
        self.export_error.connect(self._on_export_done)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def output_path(self) -> str:
        """Return the selected output file path."""
        return self._output_path

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Title
        title = QLabel("Export GIF")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # --- Settings frame ---
        settings = QFrame()
        settings.setObjectName("toolbarIsland")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(10)

        # Resolution
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Resolution:"))
        self._res_combo = QComboBox()
        self._res_combo.addItems(list(_RESOLUTION_PRESETS.keys()))
        self._res_combo.setCurrentText("480p")
        self._res_combo.currentTextChanged.connect(self._on_resolution)
        res_row.addWidget(self._res_combo)
        res_row.addStretch()
        settings_layout.addLayout(res_row)

        # Frame rate
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Frame rate:"))
        self._fps_combo = QComboBox()
        self._fps_combo.addItems(_FPS_OPTIONS)
        self._fps_combo.setCurrentText("15")
        self._fps_combo.currentTextChanged.connect(self._on_fps)
        fps_row.addWidget(self._fps_combo)
        fps_row.addWidget(QLabel("fps"))
        fps_row.addStretch()
        settings_layout.addLayout(fps_row)

        # Range
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Range:"))
        range_label = QLabel("Full clip")
        range_label.setObjectName("cardMeta")
        range_row.addWidget(range_label)
        range_row.addStretch()
        settings_layout.addLayout(range_row)

        # Output path
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self._out_input = QLineEdit(self._output_path)
        self._out_input.setReadOnly(True)
        out_row.addWidget(self._out_input, stretch=1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_output)
        out_row.addWidget(browse_btn)
        settings_layout.addLayout(out_row)

        layout.addWidget(settings)

        # --- Progress bar ---
        progress_frame = QFrame()
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        progress_layout.addWidget(self._progress)
        layout.addWidget(progress_frame)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self._export_btn = QPushButton("Export GIF")
        self._export_btn.setObjectName("accent")
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_resolution(self, text: str) -> None:
        self._resolution = text

    def _on_fps(self, text: str) -> None:
        try:
            self._fps = int(text)
        except ValueError:
            self._fps = 15

    def _on_browse_output(self) -> None:
        """Open a save dialog to choose the output GIF path."""
        os.makedirs(os.path.dirname(self._output_path), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save GIF As",
            self._output_path,
            "GIF Images (*.gif);;All Files (*)",
        )
        if path:
            self._output_path = path
            self._out_input.setText(path)

    def _on_export(self) -> None:
        """Start the GIF export in a background thread."""
        if not self._source_path:
            self.export_error.emit("No source file available for export")
            return

        w, h = _RESOLUTION_PRESETS.get(self._resolution, (480, 270))

        # Disable the button during export
        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)

        self._running = True
        thread = threading.Thread(
            target=self._run_export,
            args=(w, h),
            daemon=True,
        )
        thread.start()

    def _run_export(self, width: int, height: int) -> None:
        """Run ffmpeg palettegen + paletteuse pipeline in a subprocess.

        Uses _progress_updated signal for thread-safe UI updates.
        """
        palette_path = str(Path(self._output_path).with_suffix(".png"))

        # Step 1: palette generation
        cmd_palette = [
            "ffmpeg",
            "-y",
            "-i",
            str(self._source_path),
            "-vf",
            (f"fps={self._fps},scale={width}:{height}:flags=lanczos,palettegen=stats_mode=diff"),
            palette_path,
        ]
        try:
            _command = ExternalCommandRunner()
            _command.run(cmd_palette, timeout=120, check=True)
            self._progress_updated.emit(50)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            self.export_error.emit(f"Palette generation failed: {exc}")
            return

        # Step 2: palette use
        cmd_gif = [
            "ffmpeg",
            "-y",
            "-i",
            str(self._source_path),
            "-i",
            palette_path,
            "-lavfi",
            f"fps={self._fps},scale={width}:{height}:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
            str(self._output_path),
        ]
        try:
            _command.run(cmd_gif, timeout=120, check=True)
            self._progress_updated.emit(100)
            # Clean up palette temp file
            try:
                Path(palette_path).unlink(missing_ok=True)
            except OSError:
                logger.debug("Failed to clean up palette temp file")
            self.export_finished.emit(self._output_path)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            self.export_error.emit(f"GIF encoding failed: {exc}")

    def _finish(self) -> None:
        """Re-enable UI after export completes (called on main thread)."""
        self._running = False
        self._export_btn.setEnabled(True)
        self._progress.setVisible(False)

    def _on_export_done(self, _result: str = "") -> None:
        """Slot for export_finished / export_error signals (main thread safe)."""
        self._finish()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Cancel any running export on close."""
        self._running = False
        super().closeEvent(event)
