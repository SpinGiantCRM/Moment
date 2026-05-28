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
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from clip_tray.core.store import Store

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

        # --- Transport controls ---
        transport = QFrame()
        transport.setObjectName("toolbarIsland")
        transport_layout = QHBoxLayout(transport)
        transport_layout.setContentsMargins(8, 4, 8, 4)
        transport_layout.setSpacing(4)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(32, 28)
        self._play_btn.clicked.connect(self._toggle_play)
        transport_layout.addWidget(self._play_btn)

        transport_layout.addStretch()

        transport_layout.addWidget(QLabel("Vol"))
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(100)
        self._volume_slider.valueChanged.connect(
            lambda v: self._audio_output.setVolume(v / 100.0)
        )
        transport_layout.addWidget(self._volume_slider)

        self._mute_btn = QPushButton("🔊")
        self._mute_btn.setFixedSize(28, 28)
        self._mute_btn.clicked.connect(self._toggle_mute)
        transport_layout.addWidget(self._mute_btn)

        # --- Audio mixer row ---
        audio_mixer = QFrame()
        audio_mixer.setObjectName("toolbarIsland")
        mixer_layout = QHBoxLayout(audio_mixer)
        mixer_layout.setContentsMargins(8, 4, 8, 4)
        mixer_layout.setSpacing(8)

        mixer_layout.addWidget(QLabel("Game"))
        self._game_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._game_vol_slider.setRange(0, 200)
        self._game_vol_slider.setValue(100)
        self._game_vol_slider.setFixedWidth(80)
        mixer_layout.addWidget(self._game_vol_slider)

        mixer_layout.addWidget(QLabel("Mic"))
        self._mic_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_vol_slider.setRange(0, 200)
        self._mic_vol_slider.setValue(100)
        self._mic_vol_slider.setFixedWidth(80)
        mixer_layout.addWidget(self._mic_vol_slider)

        # --- Metadata row ---
        self._meta_label = QLabel()
        self._meta_label.setObjectName("cardMeta")

        # --- URL bar ---
        url_frame = QFrame()
        url_frame.setObjectName("toolbarIsland")
        url_layout = QHBoxLayout(url_frame)
        url_layout.setContentsMargins(8, 4, 8, 4)
        url_layout.setSpacing(4)

        self._url_input = QLineEdit()
        self._url_input.setReadOnly(True)
        self._url_input.setPlaceholderText("No URL — clip not yet uploaded")
        url_layout.addWidget(self._url_input, stretch=1)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_url)
        url_layout.addWidget(copy_btn)

        # --- Back button ---
        back_btn = QPushButton("← Grid")
        back_btn.clicked.connect(self.back_requested.emit)

        # --- Empty state ---
        self._empty_label = QLabel("Select a clip to play")
        self._empty_label.setObjectName("muted")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("font-size: 16px;")

        # --- Controls container (hidden in fullscreen) ---
        self._controls = QWidget()
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.addWidget(back_btn)
        top_row.addStretch()
        controls_layout.addLayout(top_row)
        controls_layout.addWidget(self._seek_bar)
        controls_layout.addWidget(transport)
        controls_layout.addWidget(audio_mixer)
        controls_layout.addWidget(self._meta_label)
        controls_layout.addWidget(url_frame)

        # --- Main layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        layout.addWidget(self._controls)
        layout.addWidget(self._video_widget, stretch=1)
        layout.addWidget(self._empty_label, stretch=1)

        self._empty_label.setVisible(True)
        self._video_widget.setVisible(False)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ==================================================================
    # Public API
    # ==================================================================

    def load_clip(self, clip_id: str) -> None:
        """Load a clip for playback by its database ID.

        Args:
            clip_id: UUID of the clip to load.
        """
        if self._store is None:
            return

        try:
            clip = self._store.get_clip(clip_id)
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
            }

            # Determine video path (encoded > source)
            video_path = self._current_clip.get("encoded_path") or self._current_clip.get("source_path", "")

            self._empty_label.setVisible(False)
            self._video_widget.setVisible(True)

            # Stop any previous playback before changing source
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(video_path))
            self._player.play()

            # Update metadata
            game = self._current_clip.get("game", "")
            size = _fmt_size(self._current_clip.get("file_size", 0))
            duration = _fmt_ms(int(self._current_clip.get("duration", 0) * 1000))
            self._meta_label.setText(f"{game}  •  {size}  •  {duration}")

            # Update URL
            r2_url = self._current_clip.get("r2_url", "")
            self._url_input.setText(r2_url)

            self._play_btn.setText("⏸")
            logger.info("Loaded clip: %s", self._current_clip["title"])

        except Exception as exc:
            logger.exception("Failed to load clip %s", clip_id)
            self._show_empty(f"Error loading clip: {exc}")

    def stop(self) -> None:
        """Stop playback and release the media player."""
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
        elif key == Qt.Key.Key_Escape:
            if self._fullscreen:
                self._toggle_fullscreen()
            else:
                self.back_requested.emit()
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
