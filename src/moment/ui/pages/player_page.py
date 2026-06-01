"""Player page — video playback, transport overlay, seek bar, metadata, and actions.

Layout (ui-revamp Phase 4)::

    ┌──────────────────────────────────────────┐
    │                                          │
    │  Video Display  (#0a0a0a bg, aspect)     │
    │                                          │
    │  ┌─ Transport overlay (48px, auto-hide) ┐│
    │  │ 0:00  ═══════●═══════  2:30        ││
    │  |◁  ▶/⏸  ▻|  🔊 ═══  |      [⛶]  ││
    │  └──────────────────────────────────────┘│
    ├──────────────────────────────────────────┤
    │  Clip Title (18px bold)                  │
    │  [Game] · Date · Duration · Size   [Btns]│
    └──────────────────────────────────────────┘

Provides QVideoWidget playback, custom-painted seek bar, transport
controls overlay with auto-hide, metadata row, and action buttons.
Keyboard shortcuts preserved (Space/K, Arrows, F, Esc, etc.).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from moment.ui.editor.editor_window import EditorWindow
from moment.ui.services.async_loader import AsyncDataLoader

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as ``M:SS`` or ``H:MM:SS``."""
    total = max(abs(ms) // 1000, 0)
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


# ---------------------------------------------------------------------------
# Seek Bar — custom-painted
# ---------------------------------------------------------------------------


class SeekBar(QWidget):
    """Custom seek bar with track, fill, hidden thumb, and time labels.

    - 4px track, expands to 6px on hover
    - Track bg: rgba(255,255,255,0.2), fill: #4a9eff
    - Thumb: hidden by default, 14px white circle + 2px blue border on hover
    - 24px hit area
    - Click/drag to seek
    - Time labels at ends (11px monospace)
    """

    seeked = pyqtSignal(int)  # position in ms

    TRACK_HEIGHT = 4
    TRACK_HOVER_HEIGHT = 6
    THUMB_RADIUS = 7
    THUMB_BORDER = 2
    HIT_HEIGHT = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._position_ms = 0
        self._hovering = False
        self._dragging = False
        self._thumb_visible = False

        self.setMinimumHeight(self.HIT_HEIGHT)
        self.setMaximumHeight(self.HIT_HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Try to get a monospace font for time labels
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        if not mono.exactMatch():
            mono = QFont("monospace", 10)
        self._mono_font = QFont(mono)
        self._mono_font.setPointSize(10)

    # ── Public API ────────────────────────────────────────────────────

    def set_duration(self, ms: int) -> None:
        """Set the total duration in milliseconds."""
        self._duration_ms = max(ms, 1)
        self.update()

    def set_position(self, ms: int) -> None:
        """Update the current position without emitting ``seeked``."""
        if not self._dragging:
            self._position_ms = ms
            self.update()

    # ── Paint ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        track_y = (h - (self.TRACK_HOVER_HEIGHT if self._hovering else self.TRACK_HEIGHT)) // 2
        track_h = self.TRACK_HOVER_HEIGHT if self._hovering else self.TRACK_HEIGHT
        thumb_r = self.THRUMB_RADIUS

        label_w = 44  # space for time labels on each side
        track_l = label_w + 4
        track_r = w - label_w - 4
        track_w = track_r - track_l

        # ── Time labels ──────────────────────────────────────────────
        p.setFont(self._mono_font)
        p.setPen(QColor("#ffffff"))
        # Elapsed (left)
        p.drawText(
            QRect(0, 0, label_w, h),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            _fmt_ms(self._position_ms),
        )
        # Total (right)
        p.setPen(QColor("#a0a0a0"))
        p.drawText(
            QRect(w - label_w, 0, label_w, h),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            _fmt_ms(self._duration_ms),
        )

        # ── Track background ─────────────────────────────────────────
        track_rect = QRectF(float(track_l), float(track_y), float(track_w), float(track_h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 51))  # rgba(255,255,255,0.2)
        p.drawRoundedRect(track_rect, float(track_h) / 2, float(track_h) / 2)

        # ── Fill ─────────────────────────────────────────────────────
        if self._duration_ms > 0:
            fraction = min(self._position_ms / self._duration_ms, 1.0)
            fill_w = int(track_w * fraction)
            if fill_w > 0:
                fill_rect = QRectF(
                    float(track_l),
                    float(track_y),
                    float(fill_w),
                    float(track_h),
                )
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#4a9eff"))
                p.drawRoundedRect(fill_rect, float(track_h) / 2, float(track_h) / 2)

        # ── Thumb (visible on hover or drag) ─────────────────────────
        if self._thumb_visible and self._duration_ms > 0:
            fraction = min(self._position_ms / self._duration_ms, 1.0)
            thumb_x = track_l + int(track_w * fraction)
            thumb_y = h // 2

            # Outer ring (blue)
            p.setPen(QPen(QColor("#4a9eff"), self.THRUMB_BORDER))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPoint(thumb_x, thumb_y), thumb_r, thumb_r)

        p.end()

    # ── Mouse events ──────────────────────────────────────────────────

    def _x_to_ms(self, x: int) -> int:
        """Convert an x-coordinate to a millisecond position."""
        label_w = 44
        track_l = label_w + 4
        track_r = self.width() - label_w - 4
        track_w = max(track_r - track_l, 1)
        fraction = max(0.0, min(1.0, (x - track_l) / track_w))
        return int(fraction * self._duration_ms)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._thumb_visible = True
            pos = self._x_to_ms(int(event.position().x()))
            self._position_ms = pos
            self.update()
            self.seeked.emit(pos)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            pos = self._x_to_ms(int(event.position().x()))
            self._position_ms = pos
            self.update()
            self.seeked.emit(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if not self._hovering:
                self._thumb_visible = False
                self.update()

    def enterEvent(self, event) -> None:
        self._hovering = True
        self._thumb_visible = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovering = False
        if not self._dragging:
            self._thumb_visible = False
            self.update()


# ---------------------------------------------------------------------------
# Player Page
# ---------------------------------------------------------------------------


class PlayerPage(QWidget):
    """Player page with video playback, transport overlay, and metadata.

    Signals:
        back_requested: Emitted when the user clicks the back button or
            presses Esc (if not fullscreen / playing).
        fullscreen_toggled(bool): Emitted when fullscreen state changes.
        share_requested: Emitted when Share is clicked.
        download_requested: Emitted when Download is clicked.
        edit_requested: Emitted when Edit is clicked.
        delete_requested: Emitted when Delete is clicked.
    """

    back_requested = pyqtSignal()
    fullscreen_toggled = pyqtSignal(bool)
    share_requested = pyqtSignal()
    download_requested = pyqtSignal()
    edit_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, store: "Store | None" = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._current_clip: dict[str, Any] | None = None
        self._fullscreen = False
        self._controls_visible = True

        # ── Media player ─────────────────────────────────────────────────
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.8)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        # ── Controls auto-hide timer ─────────────────────────────────────
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(3000)
        self._hide_timer.timeout.connect(self._fade_out_controls)

        # ── Controls fade animation ──────────────────────────────────────
        self._controls_opacity = QGraphicsOpacityEffect()
        self._controls_opacity.setOpacity(1.0)

        # ── Build layout ─────────────────────────────────────────────────
        self._build_ui()

        # ── Editor reference ─────────────────────────────────────────────
        self._editor: EditorWindow | None = None

        # ── Async loader ─────────────────────────────────────────────────
        self._loader: AsyncDataLoader | None = None

        # Show empty state by default
        self._show_empty("Select a clip to preview")

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ==================================================================
    # UI Construction
    # ==================================================================

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Video display area ───────────────────────────────────────────
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background-color: #0a0a0a; border: none;")
        self._video_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._video_container.setMouseTracking(True)
        self._video_container.mouseMoveEvent = self._on_video_hover
        self._video_container.mouseDoubleClickEvent = self._on_double_click

        # Video widget (inside container)
        self._video_widget = QVideoWidget(self._video_container)
        self._video_widget.setMinimumSize(640, 360)
        self._video_widget.setMouseTracking(True)
        self._player.setVideoOutput(self._video_widget)
        # Also track mouse on the video widget directly (needed for fullscreen)
        self._video_widget.mouseMoveEvent = self._on_video_widget_hover

        # Stack: video fills container, transport overlay at bottom
        video_layout = QVBoxLayout(self._video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        video_layout.addWidget(self._video_widget, stretch=1)

        # ── Transport overlay (semi-transparent, at bottom of video) ────
        self._transport_overlay = self._build_transport_overlay()
        self._transport_overlay.setGraphicsEffect(self._controls_opacity)
        video_layout.addWidget(self._transport_overlay)

        # ── Empty state (shown when no clip loaded) ────────────────────
        self._empty_state = self._build_empty_state()
        self._empty_state.setVisible(True)
        layout.addWidget(self._empty_state)

        # ── Loading spinner ──────────────────────────────────────────
        self._spinner_label = QLabel("Loading…")
        self._spinner_label.setObjectName("pageTitle")
        self._spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spinner_label.setStyleSheet(
            "font-size: 20px; color: var(--text-secondary); background: transparent;"
        )
        self._spinner_label.setVisible(False)
        layout.addWidget(self._spinner_label)

        # ── Video display area (hidden until clip loaded) ─────────────
        layout.addWidget(self._video_container, stretch=1)

        # ── Metadata + actions row ───────────────────────────────────────
        self._meta_section = self._build_meta_section()
        self._meta_section.setVisible(False)
        layout.addWidget(self._meta_section)

        # Start with video hidden
        self._video_widget.setVisible(False)

    def _build_transport_overlay(self) -> QWidget:
        """Build the semi-transparent transport controls overlay."""
        overlay = QWidget()
        overlay.setObjectName("transportOverlay")
        overlay.setFixedHeight(48)
        overlay.setStyleSheet("""
            QWidget#transportOverlay {
                background-color: rgba(0, 0, 0, 0.70);
                border: none;
            }
        """)
        overlay.setMouseTracking(True)

        outer = QVBoxLayout(overlay)
        outer.setContentsMargins(8, 2, 8, 4)
        outer.setSpacing(1)

        # ── Seek bar ──────────────────────────────────────────────────
        self._seek_bar = SeekBar()
        self._seek_bar.seeked.connect(self._player.setPosition)
        outer.addWidget(self._seek_bar)

        # ── Controls row ──────────────────────────────────────────────
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(8, 0, 8, 0)
        controls_row.setSpacing(6)
        controls_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_color = "#e0e0e0"

        # Skip back 10s
        self._skip_back_btn = self._make_icon_button(
            "skip-back",
            "Skip back 10s",
            icon_color,
            24,
        )
        self._skip_back_btn.clicked.connect(self._skip_back)
        controls_row.addWidget(self._skip_back_btn)

        # Play / Pause (larger)
        self._play_btn = self._make_icon_button(
            "play",
            "Play",
            icon_color,
            28,
        )
        self._play_btn.clicked.connect(self._toggle_play)
        controls_row.addWidget(self._play_btn)

        # Skip forward 10s
        self._skip_fwd_btn = self._make_icon_button(
            "skip-forward",
            "Skip forward 10s",
            icon_color,
            24,
        )
        self._skip_fwd_btn.clicked.connect(self._skip_forward)
        controls_row.addWidget(self._skip_fwd_btn)

        controls_row.addSpacing(12)

        # Volume icon + mute toggle
        self._volume_icon_btn = self._make_icon_button(
            "volume",
            "Mute",
            icon_color,
            24,
        )
        self._volume_icon_btn.clicked.connect(self._toggle_mute)
        controls_row.addWidget(self._volume_icon_btn)

        # Volume slider
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(80)
        self._volume_slider.setFixedWidth(80)
        self._volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: rgba(255,255,255,0.15);
                border-radius: 2px; height: 4px;
            }
            QSlider::handle:horizontal {
                background-color: #ffffff; border: none;
                border-radius: 6px; width: 12px; height: 12px; margin: -4px 0;
            }
            QSlider::sub-page:horizontal {
                background-color: #e0e0e0; border-radius: 2px;
            }
        """)
        self._volume_slider.valueChanged.connect(lambda v: self._audio_output.setVolume(v / 100.0))
        controls_row.addWidget(self._volume_slider)

        controls_row.addStretch()

        # Fullscreen toggle
        self._fullscreen_btn = self._make_icon_button(
            "fullscreen",
            "Fullscreen",
            icon_color,
            24,
        )
        self._fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        controls_row.addWidget(self._fullscreen_btn)

        outer.addLayout(controls_row)

        return overlay

    def _make_icon_button(
        self,
        icon_name: str,
        tooltip: str,
        color: str,
        size: int,
    ) -> QToolButton:
        """Create a transparent QToolButton with an SVG icon."""
        from moment.ui.resources import load_icon

        btn = QToolButton()
        btn.setIcon(load_icon(icon_name, color))
        btn.setIconSize(QSize(size, size))
        btn.setToolTip(tooltip)
        btn.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
            }
            QToolButton:hover {
                background-color: rgba(255,255,255,0.10);
                border-radius: 4px;
            }
        """)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build_empty_state(self) -> QWidget:
        """Build the empty state: icon + 'Select a clip to preview'."""
        from moment.ui.resources import load_icon

        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon_label = QLabel()
        icon = load_icon("empty-library", "#555555")
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        heading = QLabel("Select a clip to preview")
        heading.setObjectName("emptyStateHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            "color: var(--text-secondary); font-size: 16px; background: transparent;"
        )
        layout.addWidget(heading)

        return widget

    def _build_meta_section(self) -> QWidget:
        """Build the metadata row + action buttons below the video."""
        section = QWidget()
        section.setStyleSheet("""
            QWidget {
                background-color: var(--bg-window);
                border-top: 1px solid var(--border-subtle);
            }
        """)

        layout = QHBoxLayout(section)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        # ── Left: metadata ────────────────────────────────────────────
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(4)

        self._title_label = QLabel()
        self._title_label.setObjectName("playerTitle")
        self._title_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: var(--text-primary);"
            "background: transparent;"
        )
        meta_layout.addWidget(self._title_label)

        self._info_label = QLabel()
        self._info_label.setObjectName("playerInfo")
        self._info_label.setStyleSheet(
            "font-size: 13px; color: var(--text-secondary); background: transparent;"
        )
        meta_layout.addWidget(self._info_label)

        layout.addLayout(meta_layout, stretch=1)

        # ── Right: action buttons ─────────────────────────────────────
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Share (primary)
        self._share_btn = QPushButton("Share")
        self._share_btn.setObjectName("primary")
        self._share_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._share_btn.clicked.connect(self.share_requested.emit)
        actions_layout.addWidget(self._share_btn)

        # Download (primary)
        self._download_btn = QPushButton("Download")
        self._download_btn.setObjectName("primary")
        self._download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_btn.clicked.connect(self.download_requested.emit)
        actions_layout.addWidget(self._download_btn)

        # Edit (secondary — line style)
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("secondary")
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        self._edit_btn.clicked.connect(self.edit_requested.emit)
        actions_layout.addWidget(self._edit_btn)

        # Delete (danger — line style)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.clicked.connect(self.delete_requested.emit)
        actions_layout.addWidget(self._delete_btn)

        layout.addLayout(actions_layout)

        return section

    # ==================================================================
    # Public API
    # ==================================================================

    def load_clip(self, clip_id: str) -> None:
        """Load a clip for playback by its database ID asynchronously.

        Shows a loading spinner immediately, cancels any in-flight loader,
        then loads clip data on a background thread.
        """
        if self._store is None:
            return

        self._cancel_loader()

        # Show loading state
        self._empty_state.setVisible(False)
        self._video_container.setVisible(False)
        self._video_widget.setVisible(False)
        self._spinner_label.setVisible(True)

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
            "created_at": getattr(clip, "created_at", None),
            "favorite": getattr(clip, "favorite", False),
        }

        video_path = self._current_clip.get("encoded_path") or self._current_clip.get(
            "source_path", ""
        )

        # Show video area
        self._empty_state.setVisible(False)
        self._video_container.setVisible(True)
        self._video_widget.setVisible(True)
        self._meta_section.setVisible(True)

        # Start playback
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(video_path))
        self._player.play()

        # Update metadata
        self._update_metadata()
        self._update_play_icon("pause")

        # Show controls overlay
        self._show_controls()

        logger.info("Loaded clip: %s", self._current_clip["title"])

    def _update_metadata(self) -> None:
        """Populate the metadata section from the current clip."""
        if self._current_clip is None:
            return

        clip = self._current_clip
        self._title_label.setText(clip["title"])

        parts: list[str] = []

        # Game pill
        game = clip.get("game", "")
        if game:
            parts.append(game)

        # Date
        created = clip.get("created_at")
        if created:
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created)
                except ValueError:
                    created = None
            if isinstance(created, datetime):
                parts.append(created.strftime("%b %d, %Y"))
            else:
                parts.append(str(created)[:10])

        # Duration
        dur = clip.get("duration", 0)
        if dur:
            parts.append(_fmt_ms(int(float(dur) * 1000)))

        # File size
        size = clip.get("file_size", 0)
        if size:
            parts.append(_fmt_size(int(size)))

        self._info_label.setText(" · ".join(parts))

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

    def stop(self) -> None:
        """Stop playback, cancel loader, and release the media player."""
        self._cancel_loader()
        self._player.stop()
        self._player.setSource(QUrl())

    # ==================================================================
    # Transport controls visibility
    # ==================================================================

    def _show_controls(self) -> None:
        """Show the transport overlay (cancel any hide timer)."""
        self._hide_timer.stop()

        if not self._controls_visible:
            self._controls_visible = True
            self._fade_controls(0.0, 1.0)

        # Restart hide timer (3s) — but only if actually playing
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._hide_timer.start()

    def _fade_out_controls(self) -> None:
        """Fade out the transport overlay after inactivity."""
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._controls_visible = False
            self._fade_controls(1.0, 0.0)

    def _fade_controls(self, from_val: float, to_val: float) -> None:
        """Animate the transport overlay opacity over 200ms."""
        anim = QPropertyAnimation(self._controls_opacity, b"opacity")
        anim.setDuration(200)
        anim.setStartValue(from_val)
        anim.setEndValue(to_val)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.start()
        # Keep a reference to prevent garbage collection
        setattr(self, "_fade_anim", anim)

    def _on_video_hover(self, event) -> None:
        """Show controls when hovering over the video container."""
        self._show_controls()
        QWidget.mouseMoveEvent(self._video_container, event)

    def _on_video_widget_hover(self, event) -> None:
        """Show controls when hovering over the video widget (needed in fullscreen)."""
        if self._fullscreen:
            self._show_controls()
        QVideoWidget.mouseMoveEvent(self._video_widget, event)

    # ==================================================================
    # Playback controls
    # ==================================================================

    def _toggle_play(self) -> None:
        """Toggle between play and pause."""
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._update_play_icon("play")
            # Keep controls visible while paused
            self._hide_timer.stop()
            if not self._controls_visible:
                self._show_controls()
        else:
            self._player.play()
            self._update_play_icon("pause")
            self._hide_timer.start()

    def _update_play_icon(self, state: str) -> None:
        """Swap the play button icon between play and pause."""
        from moment.ui.resources import load_icon

        self._play_btn.setIcon(load_icon(state, "#e0e0e0"))
        self._play_btn.setText("Play" if state == "play" else "Pause")

    def _skip_back(self) -> None:
        """Skip back 10 seconds."""
        new_pos = max(0, self._player.position() - 10000)
        self._player.setPosition(new_pos)

    def _skip_forward(self) -> None:
        """Skip forward 10 seconds."""
        new_pos = min(self._player.duration(), self._player.position() + 10000)
        self._player.setPosition(new_pos)

    def _toggle_mute(self) -> None:
        """Toggle mute on the audio output."""
        from moment.ui.resources import load_icon

        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        if muted:
            self._volume_icon_btn.setIcon(load_icon("volume-muted", "#e0e0e0"))
            self._volume_icon_btn.setToolTip("Unmute")
        else:
            self._volume_icon_btn.setIcon(load_icon("volume", "#e0e0e0"))
            self._volume_icon_btn.setToolTip("Mute")

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
            # Always show controls in fullscreen initially
            self._show_controls()

            # Remove from layout and make it a top-level window
            self._video_widget.setParent(None)
            self._video_widget.setWindowFlags(Qt.WindowType.Window)
            # Need to re-apply mouse tracking after reparenting
            self._video_widget.setMouseTracking(True)
            self._video_widget.mouseMoveEvent = self._on_video_widget_hover
            self._video_widget.mouseDoubleClickEvent = self._on_double_click
            self._video_widget.showFullScreen()

            # Reparent the transport overlay to the video widget
            self._transport_overlay.setParent(self._video_widget)
            self._transport_overlay.setGeometry(
                0,
                self._video_widget.height() - 48,
                self._video_widget.width(),
                48,
            )
        else:
            # Exit fullscreen
            self._video_widget.setWindowFlags(Qt.WindowType.Widget)
            self._video_widget.showNormal()

            # Re-parent back
            self._video_widget.setParent(self._video_container)
            self._video_container.layout().insertWidget(0, self._video_widget, stretch=1)

            self._transport_overlay.setParent(self._video_container)
            self._video_container.layout().addWidget(self._transport_overlay)

            self._show_controls()

        self.fullscreen_toggled.emit(self._fullscreen)

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
    # Editor window
    # ==================================================================

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

    # ==================================================================
    # States
    # ==================================================================

    def _show_empty(self, message: str) -> None:
        """Show the empty-state placeholder."""
        self._spinner_label.setVisible(False)
        self._video_container.setVisible(False)
        self._meta_section.setVisible(False)
        # Update the heading text and show
        heading = self._empty_state.findChild(QLabel, "emptyStateHeading")
        if heading:
            heading.setText(message)
        self._empty_state.setVisible(True)

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
            # Handled context-aware by MainWindow QShortcut
            return
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            fraction = (key - Qt.Key.Key_0) / 10.0
            duration = self._player.duration()
            if duration > 0:
                self._player.setPosition(int(duration * fraction))
        else:
            super().keyPressEvent(event)
