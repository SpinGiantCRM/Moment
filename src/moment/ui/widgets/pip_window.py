"""PiP (Picture-in-Picture) window — frameless floating QPixmap-based player.

Uses ffmpeg to extract frames as raw RGB24 via pipe — intentionally does NOT
use QVideoWidget, which would contend for the GPU context during active games.

Features:
- 320×180 frameless, always-on-top, positioned bottom-right of primary screen
- Frame-by-frame playback via ffmpeg pipe at source FPS (capped at 30)
- Auto-closes after 30s; timer resets on mouse hover
- Click opens the normal player with the clip
- Close button (×) in top-right corner
- Source-file-deleted detection → "Not found" overlay
- Rapid PiP requests → only the last one stays (singleton-per-clip)

Usage::

    window = PipWindow(clip_id="abc", source_path="/path/to/source.mkv", store=store)
    window.show_pip()
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 — required for PIPE, DEVNULL, TimeoutExpired
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.resources import color
from moment.utils.subprocess import ExternalCommandRunner

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PIP_W = 320
_PIP_H = 180
_OFFSET = 24  # px from screen edge
_CLOSE_BTN_SIZE = 20
_MAX_FPS = 30
_AUTO_CLOSE_MS = 30000  # 30s


class PipWindow(QWidget):
    """Frameless floating PiP playback window.

    Signals:
        clip_clicked(str): Emitted with the clip ID when the window is clicked.
        closed: Emitted when the window closes.
    """

    clip_clicked = pyqtSignal(str)
    pip_closed = pyqtSignal(str)

    def __init__(
        self,
        clip_id: str,
        source_path: Path | str,
        fps: float = 30.0,
        store: "Store | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(None)  # no parent — frameless tool window
        self._clip_id = clip_id
        self._source_path = Path(source_path) if isinstance(source_path, str) else source_path
        self._fps = min(fps, _MAX_FPS) if fps > 0 else _MAX_FPS
        self._store = store
        self._parent = parent

        # ffmpeg subprocess handle
        self._ffmpeg_proc: object | None = None  # subprocess.Popen
        self._frame_timer: QTimer | None = None
        self._current_frame = 0
        self._total_frames = 0
        self._restart_count = 0
        self._running = False

        # Threading primitives (initialized here, populated in _start_playback)
        self._frame_buffer: bytes | None = None
        self._frame_lock: object | None = None  # threading.Lock
        self._reader_thread: object | None = None  # threading.Thread
        self._source_exists = self._source_path.is_file()

        # --- Window setup ---
        self.setFixedSize(_PIP_W, _PIP_H)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(f"background-color: {color('--bg-surface')}; border-radius: 6px;")

        # --- Auto-close timer ---
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(_AUTO_CLOSE_MS)
        self._close_timer.timeout.connect(self.close)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # Image display label
        self._image_label = QLabel()
        self._image_label.setFixedSize(_PIP_W - 4, _PIP_H - 4)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: transparent; border: none;")
        self._image_label.mousePressEvent = self._on_clicked
        layout.addWidget(self._image_label)

        # Close button (overlaid top-right via absolute positioning)
        self._close_btn = QPushButton("×", self)
        self._close_btn.setFixedSize(_CLOSE_BTN_SIZE, _CLOSE_BTN_SIZE)
        self._close_btn.move(_PIP_W - _CLOSE_BTN_SIZE - 4, 4)
        self._close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(0, 0, 0, 0.5);
                color: {color("--text-primary")};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(248, 113, 113, 0.8);
            }}
            """
        )
        self._close_btn.clicked.connect(self.close)
        self._close_btn.raise_()

        # Show initial placeholder
        self._show_placeholder()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_pip(self) -> None:
        """Position the window and start playback."""
        self._position()
        self.show()
        self._close_timer.start()

        if self._source_exists:
            self._start_playback()
        else:
            self._show_not_found()

    def stop(self) -> None:
        """Stop playback and clean up the ffmpeg subprocess."""
        self._stop_playback()

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position(self) -> None:
        """Position in the bottom-right of the primary monitor with offset."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return

        geom: QRect = screen.availableGeometry()
        x = geom.right() - _PIP_W - _OFFSET
        y = geom.bottom() - _PIP_H - _OFFSET
        self.move(x, y)

    # ------------------------------------------------------------------
    # Playback via ffmpeg pipe
    # ------------------------------------------------------------------

    def _start_playback(self) -> None:
        """Spawn ffmpeg to extract frames as raw RGB24 via pipe."""
        self._restart_count = 0
        self._frame_timer = QTimer(self)
        frame_interval = int(1000 / self._fps)

        # Count total frames for loop detection
        try:
            _command = ExternalCommandRunner()
            probe = _command.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-count_packets",
                    "-show_entries",
                    "stream=nb_read_packets",
                    "-of",
                    "csv=p=0",
                    str(self._source_path),
                ],
                text=True,
                timeout=10,
            )
            self._total_frames = int(probe.stdout.strip() or 0)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            self._total_frames = 0

        try:
            # ffmpeg pipe: rawvideo rgb24, one frame at a time
            self._ffmpeg_proc = _command.run_popen(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-i",
                    str(self._source_path),
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-vframes",
                    "0",  # all frames
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            # Read frames in a background thread, push to main thread via timer
            self._frame_lock = threading.Lock()
            self._frame_buffer = None
            self._running = True

            def _read_loop() -> None:
                """Continuously read frames from ffmpeg stdout."""
                frame_bytes = _PIP_W * _PIP_H * 3  # RGB24 = 3 bytes per pixel
                while self._running and self._ffmpeg_proc is not None:
                    try:
                        data = self._ffmpeg_proc.stdout.read(frame_bytes)  # type: ignore[union-attr]
                        if not data or len(data) < frame_bytes:
                            break
                        with self._frame_lock:
                            self._frame_buffer = data
                    except (OSError, ValueError):
                        break

            self._reader_thread = threading.Thread(target=_read_loop, daemon=True)
            self._reader_thread.start()

            # Timer ticks at playback rate, pulls latest frame from buffer
            self._frame_timer.timeout.connect(self._on_frame_tick)
            self._frame_timer.start(frame_interval)

        except (FileNotFoundError, OSError) as exc:
            logger.warning("Failed to start ffmpeg for PiP: %s", exc)
            self._show_not_found()

    def _on_frame_tick(self) -> None:
        """Pull the latest frame from the buffer and display it."""
        with self._frame_lock:
            data = self._frame_buffer
            self._frame_buffer = None

        if data is not None and len(data) >= _PIP_W * _PIP_H * 3:
            image = QImage(data, _PIP_W, _PIP_H, QImage.Format.Format_RGB888)
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self._image_label.setPixmap(
                    pixmap.scaled(
                        _PIP_W - 4,
                        _PIP_H - 4,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._current_frame += 1
                return

        # End of stream — loop back or stop
        if self._current_frame > 0 and self._restart_count < 3:
            # Loop: restart playback (capped at 3 loops)
            self._stop_playback()
            self._current_frame = 0
            self._restart_count += 1
            self._start_playback()

    def _stop_playback(self) -> None:
        """Kill the ffmpeg subprocess and stop the timer."""
        self._running = False

        if self._frame_timer is not None:
            self._frame_timer.stop()
            self._frame_timer = None

        if self._ffmpeg_proc is not None:
            try:
                self._ffmpeg_proc.stdout.close()  # type: ignore[union-attr]
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=3)
            except Exception:
                try:
                    self._ffmpeg_proc.kill()
                except Exception:
                    logger.debug("Failed to kill ffmpeg process for PiP")  # nosec B110
            self._ffmpeg_proc = None

    # ------------------------------------------------------------------
    # States / overlays
    # ------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        """Show a dark placeholder before playback starts."""
        placeholder = QPixmap(_PIP_W - 4, _PIP_H - 4)
        placeholder.fill(QColor(color("--bg-elevated")))
        self._image_label.setPixmap(placeholder)

    def _show_not_found(self) -> None:
        """Show a 'Not found' overlay."""
        placeholder = QPixmap(_PIP_W - 4, _PIP_H - 4)
        placeholder.fill(QColor(color("--bg-elevated")))
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(color("--text-muted")))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            QRect(0, 0, _PIP_W - 4, _PIP_H - 4),
            Qt.AlignmentFlag.AlignCenter,
            "Not found",
        )
        painter.end()
        self._image_label.setPixmap(placeholder)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_clicked(self, event: object) -> None:
        """Emit clip_clicked when the image area is clicked."""
        self.clip_clicked.emit(self._clip_id)
        self.close()

    def enterEvent(self, event: object) -> None:
        """Pause auto-close timer on hover."""
        super().enterEvent(event)
        self._close_timer.stop()

    def leaveEvent(self, event: object) -> None:
        """Restart auto-close timer on leave."""
        super().leaveEvent(event)
        self._close_timer.start()

    def closeEvent(self, event: object) -> None:
        """Clean up on close."""
        self._stop_playback()
        self.pip_closed.emit(self._clip_id)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Singleton — rapid PiP requests only keep the last one
    # ------------------------------------------------------------------

    _active: dict[str, PipWindow] = {}

    @classmethod
    def show_for_clip(
        cls,
        clip_id: str,
        source_path: Path | str,
        fps: float = 30.0,
        store: "Store | None" = None,
    ) -> PipWindow:
        """Show a PiP window, replacing any existing one for the same clip.

        Only the **last** PiP request for a given clip stays open.
        """
        # Close existing window for this clip
        existing = cls._active.pop(clip_id, None)
        if existing is not None:
            try:
                existing.stop()
                existing.close()
            except RuntimeError:
                pass  # already closed

        window = cls(clip_id=clip_id, source_path=source_path, fps=fps, store=store)
        cls._active[clip_id] = window
        window.pip_closed.connect(lambda cid: cls._active.pop(cid, None))
        window.show_pip()
        return window
