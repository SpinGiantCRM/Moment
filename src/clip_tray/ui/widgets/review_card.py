"""Clip Review Card — auto-popup after clip capture.

A frameless tool window that appears bottom-right after a clip is saved.
Shows a silent thumbnail preview of the last N seconds of the source MKV,
with action buttons for quick triage: rename, trim, favorite, open player.

Sizes: Small(320×260), Medium(420×340), Large(520×420).  Max 3 visible;
4th replaces oldest.  Slide-in animation at 250ms ease-out.  Auto-dismiss
after 8s; hover pauses the timer.

When a game is active and ``WA_ShowWithoutActivating`` is set, the card
does NOT steal focus.

Usage::

    card = ClipReviewCard(clip, game_profile.review_card)
    card.show_card()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from clip_tray.core.models import Clip, ReviewCardConfig
from clip_tray.ui.resources import color

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Size presets
# ---------------------------------------------------------------------------

_SIZE_MAP: dict[str, tuple[int, int]] = {
    "small":  (320, 260),
    "medium": (420, 340),
    "large":  (520, 420),
}

_OFFSET_FROM_EDGE = 24
_GAP_BETWEEN_CARDS = 12
_MAX_VISIBLE = 3
_AUTO_DISMISS_MS = 8000
_ANIM_DURATION_MS = 250

# ---------------------------------------------------------------------------
# Global card stack
# ---------------------------------------------------------------------------

_visible_cards: list[ClipReviewCard] = []


# ===========================================================================
# ClipReviewCard
# ===========================================================================


class ClipReviewCard(QWidget):
    """Non-blocking review popup shown after clip capture."""

    closed = pyqtSignal(object)  # emitted when card is dismissed
    trim_requested = pyqtSignal(str)  # clip_id
    open_player_requested = pyqtSignal(str)  # clip_id
    rename_requested = pyqtSignal(str, str)  # clip_id, new_title

    def __init__(
        self,
        clip: Clip,
        config: ReviewCardConfig | None = None,
        game_active: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(None)  # frameless tool window — no parent
        self._clip = clip
        self._config = config or ReviewCardConfig()
        self._game_active = game_active
        self._hovered = False
        self._anim: QPropertyAnimation | None = None

        # Size
        size_str: str = self._config.size  # type: ignore[assignment]
        w, h = _SIZE_MAP.get(size_str, _SIZE_MAP["medium"])
        self.setFixedSize(w, h)

        # Window flags
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if game_active:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.setStyleSheet(f"""
            ClipReviewCard {{
                background-color: {color('--bg-surface')};
                border-radius: 6px;
            }}
        """)
        self.setObjectName("ClipReviewCard")

        # --- Build UI ---
        self._build_ui()

        # Auto-dismiss timer
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(_AUTO_DISMISS_MS)
        self._dismiss_timer.timeout.connect(self.dismiss)

        # Manage global stack
        self._register()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Thumbnail ---
        self._thumb_label = QLabel()
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background: transparent; border: none;")
        self._thumb_label.setMinimumHeight(100)
        layout.addWidget(self._thumb_label, 1)

        if self._clip.thumb_path and Path(self._clip.thumb_path).is_file():
            pixmap = QPixmap(str(self._clip.thumb_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.width() - 16, self.height() // 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._thumb_label.setPixmap(scaled)
            else:
                self._show_thumb_placeholder()
        else:
            self._show_thumb_placeholder()

        # Check source file status
        source_path = self._clip.source_path
        if source_path and not Path(source_path).is_file():
            overlay = QLabel("File not found", self._thumb_label)
            overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            overlay.setStyleSheet(
                "background: rgba(0,0,0,0.65); color: #f87171; font-size: 13px;"
                "font-weight: 600; padding: 4px 12px; border-radius: 4px;"
            )
            overlay.setFixedSize(160, 30)
            overlay.move(
                (self._thumb_label.width() - 160) // 2,
                (self._thumb_label.height() - 30) // 2,
            )

        # --- Info row ---
        info_layout = QHBoxLayout()
        info_layout.setSpacing(8)

        if self._config.show_game_name and self._clip.game:
            game_label = QLabel(self._clip.game)
            game_label.setStyleSheet(f"color: {color('--accent-blue')}; font-size: 11px; font-weight: 600;")
            info_layout.addWidget(game_label)

        if self._config.show_duration:
            dur_label = QLabel(self._fmt_duration(self._clip.duration))
            dur_label.setStyleSheet(f"color: {color('--text-secondary')}; font-size: 11px;")
            info_layout.addWidget(dur_label)

        if self._config.show_file_size:
            size_label = QLabel(self._fmt_size(self._clip.file_size))
            size_label.setStyleSheet(f"color: {color('--text-secondary')}; font-size: 11px;")
            info_layout.addWidget(size_label)

        info_layout.addStretch()
        layout.addLayout(info_layout)

        # --- Title / Rename ---
        if self._config.show_rename:
            self._rename_edit = QLineEdit(self._clip.title or self._clip.stem)
            self._rename_edit.setPlaceholderText("Clip name…")
            self._rename_edit.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {color('--bg-inset')};
                    color: {color('--text-primary')};
                    border: 1px solid {color('--border-menu')};
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 13px;
                }}
                QLineEdit:focus {{
                    border-color: {color('--accent-blue')};
                }}
            """)
            self._rename_edit.returnPressed.connect(self._on_rename)
            self._rename_edit.editingFinished.connect(self._on_rename_commit)
            layout.addWidget(self._rename_edit)

        # --- Action buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        if self._config.show_trim:
            trim_btn = QPushButton("Trim")
            trim_btn.clicked.connect(self._on_trim)
            btn_layout.addWidget(trim_btn)

        if self._config.show_favorite:
            fav_text = "★" if self._clip.favorite else "☆"
            fav_btn = QPushButton(fav_text)
            fav_btn.setFixedWidth(32)
            fav_btn.clicked.connect(self._on_favorite)
            btn_layout.addWidget(fav_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; color: #757575;
                font-size: 16px; font-weight: bold; padding: 0;
            }
            QPushButton:hover { color: #d9d9d9; }
        """)
        close_btn.clicked.connect(self.dismiss)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Click on thumbnail → open player
        self._thumb_label.mousePressEvent = lambda e: self._on_open_player()

    # ------------------------------------------------------------------
    # Show / position / animation
    # ------------------------------------------------------------------

    @pyqtProperty(QPoint)
    def _slide_pos(self) -> QPoint:
        return self.pos()

    @_slide_pos.setter  # type: ignore[no-redef]
    def _slide_pos(self, pos: QPoint) -> None:
        self.move(pos)

    def show_card(self) -> None:
        """Position at bottom-right and slide in."""
        target = self._calc_position()
        start = QPoint(target.x(), target.y() + self.height() + 40)
        self.move(start)
        self.show()
        self._dismiss_timer.start()

        self._anim = QPropertyAnimation(self, b"_slide_pos", self)
        self._anim.setDuration(_ANIM_DURATION_MS)
        self._anim.setStartValue(start)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _calc_position(self) -> QPoint:
        """Stack cards bottom-right with gaps."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(100, 100)
        geom: QRect = screen.availableGeometry()
        x = geom.right() - self.width() - _OFFSET_FROM_EDGE

        # Count visible cards that aren't this one
        other_cards = [c for c in _visible_cards if c is not self and c.isVisible()]
        offset = sum(c.height() + _GAP_BETWEEN_CARDS for c in other_cards)
        y = geom.bottom() - self.height() - _OFFSET_FROM_EDGE - offset
        return QPoint(x, max(y, geom.top()))

    # ------------------------------------------------------------------
    # Global stack management
    # ------------------------------------------------------------------

    def _register(self) -> None:
        """Add to the global visible cards stack, evicting oldest if needed."""
        global _visible_cards
        # Clean up destroyed cards (skip those not yet shown)
        _visible_cards = [c for c in _visible_cards if c.isVisible() or (hasattr(c, '_anim') and c._anim is not None)]

        if len(_visible_cards) >= _MAX_VISIBLE:
            oldest = _visible_cards[0]
            oldest.dismiss()
        _visible_cards.append(self)

    def dismiss(self) -> None:
        """Slide out and close."""
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
        # Stop in-progress show animation if any
        if self._anim is not None and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        end = QPoint(self.pos().x(), self.pos().y() + self.height() + 40)
        anim = QPropertyAnimation(self, b"_slide_pos", self)
        anim.setDuration(150)
        anim.setStartValue(self.pos())
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self._on_dismiss_done)
        anim.start()

    def _on_dismiss_done(self) -> None:
        global _visible_cards
        if self in _visible_cards:
            _visible_cards.remove(self)
        self.closed.emit(self)
        self.close()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_rename(self) -> None:
        """Rename clip on Enter and dismiss."""
        if hasattr(self, "_rename_edit") and self._rename_edit.text().strip():
            self.rename_requested.emit(self._clip.id, self._rename_edit.text().strip())
        self.dismiss()

    def _on_rename_commit(self) -> None:
        """Emit rename when focus leaves the field."""
        if hasattr(self, "_rename_edit") and self._rename_edit.text().strip():
            self.rename_requested.emit(self._clip.id, self._rename_edit.text().strip())

    def _on_trim(self) -> None:
        """Emit signal to open the trim dialog."""
        self.trim_requested.emit(self._clip.id)
        self.dismiss()

    def _on_favorite(self) -> None:
        """Toggle favorite and dismiss."""
        self._clip.favorite = not self._clip.favorite
        logger.debug("Toggled favorite for clip %s → %s", self._clip.id, self._clip.favorite)
        self.dismiss()

    def _on_open_player(self) -> None:
        """Emit signal to open the clip in the player."""
        self.open_player_requested.emit(self._clip.id)
        self.dismiss()

    # ------------------------------------------------------------------
    # Hover pause support
    # ------------------------------------------------------------------

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self._hovered = True
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._dismiss_timer.start(_AUTO_DISMISS_MS)

    # ------------------------------------------------------------------
    # Placeholder
    # ------------------------------------------------------------------

    def _show_thumb_placeholder(self) -> None:
        placeholder = QPixmap(self.width() - 16, self.height() // 2)
        placeholder.fill(QColor(color("--bg-elevated")))
        self._thumb_label.setPixmap(placeholder)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes >= 1_073_741_824:
            return f"{size_bytes / 1_073_741_824:.1f} GB"
        elif size_bytes >= 1_048_576:
            return f"{size_bytes / 1_048_576:.0f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"
