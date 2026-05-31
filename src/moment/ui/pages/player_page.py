"""Player page — clip playback with controls, audio mixer, and URL bar.

Provides a ``QVideoWidget`` for playback, a custom seek bar, per-track
audio volume sliders, metadata display, and a copyable R2 URL bar.
Keyboard shortcuts follow the spec (Space/K, Arrows, F, Esc, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from moment.ui.editor.editor_window import EditorWindow
from moment.ui.services.async_loader import AsyncDataLoader

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)


class SeekBar(QWidget):
    """Custom seek bar with elapsed/total time labels."""

    seeked = pyqtSignal(int)  # position in ms

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._position_ms = 0
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._elapsed_label = QLabel("0:00")
        self._elapsed_label.setObjectName("cardMeta")
        self._elapsed_label.setFixedWidth(40)
        layout.addWidget(self._elapsed_label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self._slider, stretch=1)

        self._total_label = QLabel("0:00")
        self._total_label.setObjectName("cardMeta")
        self._total_label.setFixedWidth(40)
        layout.addWidget(self._total_label)

    def set_duration(self, ms: int) -> None:
        """Set the total duration in milliseconds."""
        self._duration_ms = ms
        self._total_label.setText(_fmt_ms(ms))
        self._slider.setRange(0, max(ms, 1))

    def set_position(self, ms: int) -> None:
        """Update the current position without emitting ``seeked``."""
        if not self._dragging:
            self._position_ms = ms
            self._slider.blockSignals(True)
            self._slider.setValue(ms)
            self._slider.blockSignals(False)
            self._elapsed_label.setText(_fmt_ms(ms))

    def _on_slider_pressed(self) -> None:
        self._dragging = True

    def _on_slider_released(self) -> None:
        self._dragging = False
        self.seeked.emit(self._slider.value())

    def _on_slider_value_changed(self, value: int) -> None:
        if self._dragging:
            self._elapsed_label.setText(_fmt_ms(value))


class PlayerPage(QWidget):
    """Player page with video playback, controls, and metadata.

    Signals:
        back_requested: Emitted when the user clicks the back button or
            presses Esc.
        fullscreen_toggled(bool): Emitted when fullscreen state changes.
    """

    back_requested = pyqtSignal()
    fullscreen_toggled = pyqtSignal(bool)

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._current_clip: dict[str, Any] | None = None
        self._fullscreen = False
        self._hide_controls_timer = QTimer()
        self._hide_controls_timer.setSingleShot(True)
        self._hide_controls_timer.setInterval(3000)
        self._hide_controls_timer.timeout.connect(self._hide_overlay_controls)

        # --- Media player ---
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.8)

        # --- Video widget ---
        self._video_widget = QVideoWidget()
        self._video_widget.setMinimumSize(640, 360)
        self._video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._player.setVideoOutput(self._video_widget)
        self._video_widget.mouseDoubleClickEvent = self._on_double_click
        self._video_widget.mouseMoveEvent = self._on_video_mouse_move
        self._video_widget.setMouseTracking(True)

        # Player signals
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        # --- Seek bar ---
        self._seek_bar = SeekBar()
        self._seek_bar.seeked.connect(self._player.setPosition)

        # --- Transport controls (minimal, overlay-style) ---
        transport = QWidget()
        transport_layout = QHBoxLayout(transport)
        transport_layout.setContentsMargins(12, 6, 12, 6)
        transport_layout.setSpacing(8)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(36, 36)
        self._play_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: rgba(255,255,255,0.10);"
            "   color: #ffffff;"
            "   border: none;"
            "   border-radius: 18px;"
            "   font-size: 16px;"
            "}"
            "QPushButton:hover {"
            "   background-color: rgba(255,255,255,0.20);"
            "}"
        )
        self._play_btn.clicked.connect(self._toggle_play)
        transport_layout.addWidget(self._play_btn)

        transport_layout.addSpacing(8)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            "   background-color: rgba(255,255,255,0.15);"
            "   border-radius: 2px; height: 3px;"
            "}"
            "QSlider::handle:horizontal {"
            "   background-color: #ffffff; border: none;"
            "   border-radius: 6px; width: 12px; height: 12px; margin: -4px 0;"
            "}"
            "QSlider::sub-page:horizontal {"
            "   background-color: #ffffff; border-radius: 2px;"
            "}"
        )
        self._volume_slider.valueChanged.connect(
            lambda v: self._audio_output.setVolume(v / 100.0)
        )
        transport_layout.addWidget(self._volume_slider)

        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setFixedSize(32, 32)
        self._mute_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: transparent;"
            "   border: none; font-size: 14px;"
            "}"
        )
        self._mute_btn.clicked.connect(self._toggle_mute)
        transport_layout.addWidget(self._mute_btn)

        transport_layout.addStretch()

        # --- Metadata (game • size • duration) ---
        self._meta_label = QLabel()
        self._meta_label.setObjectName("cardMeta")
        self._meta_label.setStyleSheet(
            "color: #cccccc; font-size: 12px; background: transparent;"
        )
        transport_layout.addWidget(self._meta_label)

        transport_layout.addStretch()

        # --- Audio mixer (compact row inside transport) ---
        mixer_label = QLabel("Game")
        mixer_label.setStyleSheet("color: #999; font-size: 10px; background: transparent;")
        transport_layout.addWidget(mixer_label)
        self._game_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._game_vol_slider.setRange(0, 200)
        self._game_vol_slider.setValue(100)
        self._game_vol_slider.setFixedWidth(60)
        transport_layout.addWidget(self._game_vol_slider)

        mic_label = QLabel("Mic")
        mic_label.setStyleSheet("color: #999; font-size: 10px; background: transparent;")
        transport_layout.addWidget(mic_label)
        self._mic_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_vol_slider.setRange(0, 200)
        self._mic_vol_slider.setValue(100)
        self._mic_vol_slider.setFixedWidth(60)
        transport_layout.addWidget(self._mic_vol_slider)

        # --- URL bar ---
        url_row = QHBoxLayout()
        url_row.setSpacing(6)

        self._url_input = QLineEdit()
        self._url_input.setReadOnly(True)
        self._url_input.setPlaceholderText("No URL — clip not yet uploaded")
        self._url_input.setStyleSheet(
            "background-color: rgba(255,255,255,0.08);"
            "border: 1px solid rgba(255,255,255,0.10);"
            "border-radius: 4px;"
            "color: #cccccc;"
            "font-size: 12px;"
            "padding: 4px 8px;"
        )
        url_row.addWidget(self._url_input, stretch=1)

        copy_btn = QPushButton("Copy")
        copy_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: rgba(255,255,255,0.08);"
            "   color: #cccccc;"
            "   border: 1px solid rgba(255,255,255,0.10);"
            "   border-radius: 4px;"
            "   padding: 4px 12px;"
            "   font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "   background-color: rgba(255,255,255,0.15);"
            "}"
        )
        copy_btn.clicked.connect(self._copy_url)
        url_row.addWidget(copy_btn)

        # --- Back button ---
        back_btn = QPushButton("← Back")
        back_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: transparent;"
            "   color: #cccccc;"
            "   border: 1px solid rgba(255,255,255,0.15);"
            "   border-radius: 4px;"
            "   padding: 4px 12px;"
            "   font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "   background-color: rgba(255,255,255,0.10);"
            "}"
        )
        back_btn.clicked.connect(self.back_requested.emit)

        # --- Edit button ---
        edit_btn = QPushButton("✎ Edit")
        edit_btn.setToolTip("Open in advanced editor")
        edit_btn.setStyleSheet(
            "QPushButton {"
            "   background-color: rgba(88, 101, 242, 0.15);"
            "   color: var(--accent-blue);"
            "   border: 1px solid rgba(88, 101, 242, 0.25);"
            "   border-radius: 4px;"
            "   padding: 4px 12px;"
            "   font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "   background-color: rgba(88, 101, 242, 0.25);"
            "}"
        )
        edit_btn.clicked.connect(self._on_edit_clicked)

        # --- Empty state ---
        self._empty_label = QLabel("Select a clip to play")
        self._empty_label.setObjectName("muted")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("font-size: 16px;")

        # Editor window reference
        self._editor: EditorWindow | None = None

        # Loading spinner overlay
        self._spinner_label = QLabel("Loading…")
        self._spinner_label.setObjectName("pageTitle")
        self._spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner_label.setStyleSheet("font-size: 20px; color: var(--text-secondary);")
        self._spinner_label.setVisible(False)

        # Async loader
        self._loader: AsyncDataLoader | None = None

        # --- Controls overlay (translucent, overlays video) ---
        self._controls = QWidget()
        self._controls.setStyleSheet(
            "QWidget {"
            "   background-color: rgba(15, 15, 15, 0.85);"
            "   border-radius: 8px;"
            "}"
        )
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        controls_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.addWidget(back_btn)
        top_row.addWidget(edit_btn)
        top_row.addStretch()
        controls_layout.addLayout(top_row)
        controls_layout.addWidget(self._seek_bar)
        controls_layout.addWidget(transport)
        controls_layout.addLayout(url_row)

        # --- Main layout (video fills space, controls overlay at bottom) ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Video fills the page
        layout.addWidget(self._video_widget, stretch=1)
        layout.addWidget(self._empty_label, stretch=1)
        layout.addWidget(self._spinner_label, stretch=1)

        # Controls overlay at the bottom
        controls_overlay = QHBoxLayout()
        controls_overlay.setContentsMargins(12, 0, 12, 12)
        controls_overlay.addWidget(self._controls)
        layout.addLayout(controls_overlay)

        self._empty_label.setVisible(True)
        self._video_widget.setVisible(False)
        self._spinner_label.setVisible(False)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ==================================================================
    # Public API
    # ==================================================================

    def load_clip(self, clip_id: str) -> None:
        """Load a clip for playback by its database ID asynchronously.

        Shows a loading spinner immediately, cancels any in-flight loader,
        then loads clip data on a background thread.

        Args:
            clip_id: UUID of the clip to load.
        """
        if self._store is None:
            return

        # Cancel any previous loader (also disconnects signals)
        self._cancel_loader()

        # Show loading spinner
        self._empty_label.setVisible(False)
        self._video_widget.setVisible(False)
        self._spinner_label.setVisible(True)

        # Fire async load
        self._loader = AsyncDataLoader(self._store.get_clip, clip_id)
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_load_error)
        self._loader.start()

    def _on_data_ready(self, clip: Any) -> None:
        """Handle successful async clip load."""
        self._loader = None
        self._spinner_label.setVisible(False)

        if clip is None:
            self._show_empty("Clip not found")
            return

        self._current_clip = {
            "id": clip.id,
            "title": clip.title or clip.stem,
            "game": clip.game or "",
            "file_size": clip.file_size,
            "duration": clip.duration,
            "r2_url": clip.r2_url or "",
            "encoded_path": str(clip.encoded_path) if clip.encoded_path else "",
            "source_path": str(clip.source_path),
            "edit_version": getattr(clip, "edit_version", 0),
        }

        video_path = (
            self._current_clip.get("encoded_path")
            or self._current_clip.get("source_path", "")
        )

        self._empty_label.setVisible(False)
        self._video_widget.setVisible(True)

        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(video_path))
        self._player.play()

        game = self._current_clip.get("game", "")
        duration = _fmt_ms(int(self._current_clip.get("duration", 0) * 1000))
        edited = "  •  Edited" if self._current_clip.get("edit_version", 0) > 0 else ""
        self._meta_label.setText(f"{game}{edited}  •  {duration}")

        r2_url = self._current_clip.get("r2_url", "")
        self._url_input.setText(r2_url)

        self._play_btn.setText("⏸")
        logger.info("Loaded clip: %s", self._current_clip["title"])

    def _on_load_error(self, error: str) -> None:
        """Handle async load failure."""
        self._loader = None
        self._spinner_label.setVisible(False)
        logger.exception("Failed to load clip: %s", error)
        self._show_empty(f"Error loading clip: {error}")

    def _cancel_loader(self) -> None:
        """Cancel and disconnect any in-flight async loader."""
        if self._loader is not None:
            self._loader.data_ready.disconnect()
            self._loader.error_occurred.disconnect()
            self._loader.cancel()
            self._loader = None

    def hideEvent(self, event) -> None:
        """Cancel in-flight loaders when the page is hidden."""
        self._cancel_loader()
        super().hideEvent(event)

    def _on_edit_clicked(self) -> None:
        """Open the EditorWindow for the current clip."""
        if self._store is None or self._current_clip is None:
            return
        clip_id = self._current_clip["id"]
        duration = self._current_clip.get("duration", 0.0)

        self._editor = EditorWindow(
            clip_id=clip_id,
            store=self._store,
            clip_duration=duration,
            parent=self,
        )
        self._editor.close_requested.connect(self._on_editor_closed)
        self._editor.show()

    def _on_editor_closed(self) -> None:
        """Handle editor window closing."""
        if self._editor is not None:
            self._editor.close_requested.disconnect()
            self._editor = None
        # Reload the clip to reflect any edits
        if self._current_clip is not None:
            self.load_clip(self._current_clip["id"])

    def stop(self) -> None:
        """Stop playback, cancel loader, and release the media player."""
        self._cancel_loader()
        self._player.stop()
        self._player.setSource(QUrl())

    # ==================================================================
    # Playback controls
    # ==================================================================

    def _toggle_play(self) -> None:
        """Toggle between play and pause."""
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.setText("▶")
        else:
            self._player.play()
            self._play_btn.setText("⏸")

    def _toggle_mute(self) -> None:
        """Toggle mute on the audio output."""
        muted = self._audio_output.isMuted()
        self._audio_output.setMuted(not muted)
        self._mute_btn.setText("🔇" if not muted else "🔊")

    def _copy_url(self) -> None:
        """Copy the R2 URL to the clipboard."""
        url = self._url_input.text()
        if url:
            QApplication.clipboard().setText(url)
            logger.info("URL copied to clipboard")

    # ==================================================================
    # Fullscreen
    # ==================================================================

    def _on_double_click(self, event) -> None:
        """Toggle fullscreen on double-click."""
        self._toggle_fullscreen()

    def _toggle_fullscreen(self) -> None:
        """Enter or exit fullscreen mode."""
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._controls.setVisible(False)
            # Remove from layout before making it a top-level window
            idx = self.layout().indexOf(self._video_widget)
            if idx >= 0:
                self.layout().removeWidget(self._video_widget)
            self._video_widget.setParent(None)
            self._video_widget.setWindowFlags(Qt.WindowType.Window)
            self._video_widget.showFullScreen()
        else:
            self._video_widget.setWindowFlags(Qt.WindowType.Widget)
            self._video_widget.showNormal()
            # Re-parent the video widget back into the layout
            self._video_widget.setParent(self)
            self.layout().insertWidget(1, self._video_widget, stretch=1)
            self._controls.setVisible(True)

        self.fullscreen_toggled.emit(self._fullscreen)

    def _on_video_mouse_move(self, event) -> None:
        """Show controls on mouse move when in fullscreen."""
        if self._fullscreen:
            self._controls.setVisible(True)
            self._hide_controls_timer.start()
        # Call original handler
        QVideoWidget.mouseMoveEvent(self._video_widget, event)

    def _hide_overlay_controls(self) -> None:
        """Hide overlay controls after the timer expires."""
        if self._fullscreen:
            self._controls.setVisible(False)

    # ==================================================================
    # Player signal handlers
    # ==================================================================

    def _on_duration_changed(self, duration_ms: int) -> None:
        """Update the seek bar when the duration is known."""
        self._seek_bar.set_duration(duration_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        """Update the seek bar position during playback."""
        self._seek_bar.set_position(position_ms)

    def _on_player_error(self, error, error_string: str) -> None:
        """Handle media player errors."""
        logger.error("Player error: %s", error_string)
        self._show_empty(f"Playback error: {error_string}")

    # ==================================================================
    # States
    # ==================================================================

    def _show_empty(self, message: str) -> None:
        """Show the empty-state placeholder."""
        self._empty_label.setText(message)
        self._empty_label.setVisible(True)
        self._video_widget.setVisible(False)

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def keyPressEvent(self, event) -> None:
        """Handle keyboard shortcuts for playback."""
        key = event.key()

        if key == Qt.Key.Key_Space or key == Qt.Key.Key_K:
            self._toggle_play()
        elif key == Qt.Key.Key_Left:
            self._player.setPosition(self._player.position() - 5000)
        elif key == Qt.Key.Key_Right:
            self._player.setPosition(self._player.position() + 5000)
        elif key == Qt.Key.Key_J:
            self._player.setPosition(self._player.position() - 10000)
        elif key == Qt.Key.Key_L:
            self._player.setPosition(self._player.position() + 10000)
        elif key == Qt.Key.Key_Up:
            vol = min(self._audio_output.volume() + 0.1, 2.0)
            self._audio_output.setVolume(vol)
            self._volume_slider.setValue(int(vol * 100))
        elif key == Qt.Key.Key_Down:
            vol = max(self._audio_output.volume() - 0.1, 0.0)
            self._audio_output.setVolume(vol)
            self._volume_slider.setValue(int(vol * 100))
        elif key == Qt.Key.Key_M:
            self._toggle_mute()
        elif key == Qt.Key.Key_F:
            self._toggle_fullscreen()
        # Escape is handled context-aware by MainWindow QShortcut
        # (stop video → close editor → clear search → exit selection → grid)
        elif key == Qt.Key.Key_Escape:
            return
        elif key >= Qt.Key.Key_0 and key <= Qt.Key.Key_9:
            fraction = (key - Qt.Key.Key_0) / 10.0
            duration = self._player.duration()
            if duration > 0:
                self._player.setPosition(int(duration * fraction))
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as ``M:SS`` or ``H:MM:SS``."""
    total = max(ms // 1000, 0)
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _fmt_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
