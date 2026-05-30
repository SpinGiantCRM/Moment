"""Clip delegate — custom-painted grid card for Clip items.

Renders a 260×190px card with thumbnail, title overlay bar, status
badges, favorite star, and metadata rows.  Handles hover/selected
states as defined in the ONLYOFFICE-inspired design system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QModelIndex, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

CARD_W = 260
CARD_H = 190
THUMB_W = 240
THUMB_H = 135
OVERLAY_H = 28
PADDING = 8
RADIUS = 6
THUMB_RADIUS = 4

# Colours
BG_NORMAL = QColor("#333333")
BG_ELEVATED = QColor("#404040")
BG_SELECTED = QColor("#2a3a45")
BORDER_SELECTED = QColor("#60a5fa")
TEXT_PRIMARY = QColor("#d9d9d9")
TEXT_SECONDARY = QColor("#ababab")
TEXT_MUTED = QColor("#9a9a9a")
OVERLAY_DARK = QColor(0, 0, 0, 140)
ACCENT_GREEN = QColor("#4ade80")
ACCENT_ORANGE = QColor("#fb923c")
ACCENT_RED = QColor("#f87171")
ACCENT_BLUE = QColor("#60a5fa")
FAVORITE_GOLD = QColor("#fbbf24")

def _placeholder_thumb(
    size: QSize = QSize(THUMB_W, THUMB_H),
    game: str = "",
    duration: float = 0.0,
) -> QPixmap:
    """Return a deterministic placeholder thumbnail.

    Shows the game name (or a video icon) centred on a dark background.
    When duration is known it's overlaid in the bottom-right corner.

    Args:
        size: Thumbnail size in pixels.
        game: Game name to display (empty → generic "video" icon).
        duration: Clip duration in seconds for the overlay badge.
    """
    # Invalidate cache if game/duration info is richer than what's cached
    cache_key = (game, duration)
    cached = getattr(_placeholder_thumb, "_cache", None)
    if cached is None or cached.get("key") != cache_key:
        pixmap = QPixmap(size)
        pixmap.fill(QColor("#1e1e2e"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Subtle grid pattern overlay for visual texture
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#252538"))
        for row in range(0, size.height(), 16):
            for col in range(0, size.width(), 16):
                if (row // 16 + col // 16) % 2 == 0:
                    painter.drawRect(col, row, 16, 16)

        # Centred icon / game name
        painter.setPen(QColor("#525270"))
        font = painter.font()
        if game:
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            elided = painter.fontMetrics().elidedText(
                game, Qt.TextElideMode.ElideRight, size.width() - 24,
            )
            text_rect = QRectF(0, 0, size.width(), size.height() - 20)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided)
        else:
            # Generic video icon (Unicode film symbol)
            font.setPointSize(28)
            painter.setFont(font)
            painter.drawText(
                QRectF(0, 0, size.width(), size.height() - 16),
                Qt.AlignmentFlag.AlignCenter,
                "🎬",
            )

        # Duration badge (bottom-right)
        if duration > 0:
            badge_text = _format_duration(duration)
            badge_font = painter.font()
            badge_font.setPointSize(8)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(badge_text) + 8
            text_h = fm.height() + 4
            badge_x = size.width() - text_w - 6
            badge_y = size.height() - text_h - 6
            badge_rect = QRectF(badge_x, badge_y, text_w, text_h)

            painter.setPen(Qt.PenStyle.NoPen)
            bg = QColor(0, 0, 0, 160)
            painter.setBrush(bg)
            painter.drawRoundedRect(badge_rect, 3, 3)

            painter.setPen(QColor("#d9d9d9"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        painter.end()
        _placeholder_thumb._cache = {"key": cache_key, "pixmap": pixmap}  # type: ignore[attr-defined]
        return pixmap
    return _placeholder_thumb._cache["pixmap"]  # type: ignore[attr-defined]


class ClipDelegate(QStyledItemDelegate):
    """Custom painter delegate for clip grid cards (IconMode)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumb_cache: dict[tuple[str, str], QPixmap] = {}
        self._card_font = QFont()
        self._meta_font = QFont()
        self._meta_font.setPointSize(9)

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return the fixed card size."""
        return QSize(CARD_W, CARD_H)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint a complete clip card."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- Determine state ---
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # --- Card background ---
        card_rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
        if selected:
            painter.setPen(QPen(BORDER_SELECTED, 1))
            painter.setBrush(BG_SELECTED)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(BG_ELEVATED if hovered else BG_NORMAL)

        painter.drawRoundedRect(card_rect, RADIUS, RADIUS)

        # --- Shadow lift on hover ---
        if hovered and not selected:
            shadow = QColor(0, 0, 0, 50)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow)
            shadow_rect = card_rect.adjusted(0, 2, 0, 2)
            painter.drawRoundedRect(shadow_rect, RADIUS, RADIUS)

        # Redraw the card on top (shadow is underneath)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BG_ELEVATED if hovered else BG_NORMAL)
        painter.drawRoundedRect(card_rect, RADIUS, RADIUS)

        # --- Data extraction ---
        data = index.data(Qt.ItemDataRole.UserRole)
        if data is None:
            painter.restore()
            return

        # Extract fields from the data dict
        title = data.get("title") or data.get("stem", "Untitled")
        duration = data.get("duration", 0.0)
        game = data.get("game") or ""
        file_size = data.get("file_size", 0)
        status = data.get("status", "")
        favorite = data.get("favorite", False)
        thumb_path = data.get("thumb_path", "")
        clip_id = data.get("id", "")

        # --- Thumbnail area ---
        thumb_x = option.rect.x() + (CARD_W - THUMB_W) // 2
        thumb_y = option.rect.y() + PADDING
        thumb_rect = QRectF(thumb_x, thumb_y, THUMB_W, THUMB_H)

        # Clip thumbnail to rounded rect — only if painter has a valid device
        # (offscreen/headless tests may have a null paint device → skip clip)
        painter.save()
        if painter.isActive():
            clip_path = QPainterPath()
            clip_path.addRoundedRect(thumb_rect, THUMB_RADIUS, THUMB_RADIUS)
            painter.setClipPath(clip_path)

        # Draw thumbnail or placeholder
        pixmap = self._get_thumbnail(clip_id, thumb_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                THUMB_W, THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Center-crop
            src_x = max(0, (scaled.width() - THUMB_W) // 2)
            src_y = max(0, (scaled.height() - THUMB_H) // 2)
            painter.drawPixmap(
                int(thumb_rect.x()), int(thumb_rect.y()),
                scaled, src_x, src_y, THUMB_W, THUMB_H,
            )
        else:
            # Deterministic placeholder with game name + duration
            painter.drawPixmap(
                int(thumb_rect.x()), int(thumb_rect.y()),
                _placeholder_thumb(game=game, duration=duration),
            )
        painter.restore()

        # --- Thumbnail overlay bar ---
        overlay_rect = QRectF(
            thumb_x, thumb_y + THUMB_H - OVERLAY_H,
            THUMB_W, OVERLAY_H,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(OVERLAY_DARK)
        painter.drawRect(overlay_rect)

        # Title text on overlay
        painter.setPen(TEXT_PRIMARY)
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        title_rect = overlay_rect.adjusted(6, 0, -6, 0)
        elided_title = painter.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, int(title_rect.width() - 20),
        )
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, elided_title)

        # --- Status badge (top-right of thumbnail) ---
        self._draw_status_badge(painter, thumb_rect, status)

        # --- Favorite star (bottom-left of overlay) ---
        if favorite:
            self._draw_favorite_star(painter, overlay_rect)

        # --- Metadata row ---
        meta_y = thumb_y + THUMB_H + 6
        painter.setPen(TEXT_SECONDARY)
        meta_font = painter.font()
        meta_font.setPointSize(8)
        painter.setFont(meta_font)

        meta_parts: list[str] = []
        if duration > 0:
            meta_parts.append(_format_duration(duration))
        if game:
            meta_parts.append(game)
        meta_parts.append(_format_size(file_size))

        meta_text = " • ".join(meta_parts)
        meta_rect = QRectF(thumb_x, meta_y, THUMB_W, 14)
        elided_meta = painter.fontMetrics().elidedText(
            meta_text, Qt.TextElideMode.ElideRight, int(meta_rect.width()),
        )
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft, elided_meta)

        # --- Uploaded checkmark / Edited badge (second metadata row) ---
        edited = data.get("edit_version", 0) > 0
        if status == "UPLOADED":
            painter.setPen(ACCENT_GREEN)
            check_rect = QRectF(thumb_x, meta_y + 14, THUMB_W, 14)
            painter.drawText(check_rect, Qt.AlignmentFlag.AlignLeft, "✓ Uploaded")
        elif edited:
            painter.setPen(ACCENT_ORANGE)
            edit_rect = QRectF(thumb_x, meta_y + 14, THUMB_W, 14)
            painter.drawText(edit_rect, Qt.AlignmentFlag.AlignLeft, "✎ Edited")

        painter.restore()

    # ------------------------------------------------------------------
    # Badge helpers
    # ------------------------------------------------------------------

    def _draw_status_badge(self, painter: QPainter, thumb_rect: QRectF, status: str) -> None:
        """Draw a small status indicator in the top-right of the thumbnail."""
        badge_x = thumb_rect.right() - 20
        badge_y = thumb_rect.top() + 6
        badge_r = 7

        color_map = {
            "UPLOADED": ACCENT_GREEN,
            "DONE": ACCENT_GREEN,
            "ENCODING": ACCENT_BLUE,
            "UPLOADING": ACCENT_BLUE,
            "QUEUED": ACCENT_ORANGE,
            "PENDING": ACCENT_ORANGE,
            "ERROR": ACCENT_RED,
            "CORRUPT": ACCENT_RED,
        }
        badge_color = color_map.get(status, TEXT_MUTED)

        # Draw semi-transparent background circle
        painter.setPen(Qt.PenStyle.NoPen)
        bg = QColor(badge_color)
        bg.setAlpha(40)
        painter.setBrush(bg)
        painter.drawEllipse(
            QRectF(badge_x - badge_r, badge_y - badge_r, badge_r * 2, badge_r * 2),
        )

        # Draw colored dot
        painter.setBrush(badge_color)
        dot_r = 4
        painter.drawEllipse(
            QRectF(badge_x - dot_r, badge_y - dot_r, dot_r * 2, dot_r * 2),
        )

    def _draw_favorite_star(self, painter: QPainter, overlay_rect: QRectF) -> None:
        """Draw a gold star in the bottom-left of the overlay bar."""
        painter.setPen(FAVORITE_GOLD)
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        star_rect = QRectF(
            overlay_rect.x() + 4,
            overlay_rect.y(),
            20,
            overlay_rect.height(),
        )
        painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")

    # ------------------------------------------------------------------
    # Thumbnail cache
    # ------------------------------------------------------------------

    def _get_thumbnail(self, clip_id: str, thumb_path: str) -> QPixmap:
        """Return a cached thumbnail pixmap, loading from disk if needed."""
        cache_key = (clip_id, thumb_path)
        cached = self._thumb_cache.get(cache_key)
        if cached is not None:
            return cached

        if thumb_path:
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                self._thumb_cache[cache_key] = pixmap
                # Limit cache size
                if len(self._thumb_cache) > 250:
                    # Remove oldest entry
                    oldest = next(iter(self._thumb_cache))
                    del self._thumb_cache[oldest]
                return pixmap

        # Store empty pixmap as cache miss marker
        empty = QPixmap()
        self._thumb_cache[cache_key] = empty
        return empty

    def clear_thumb_cache(self) -> None:
        """Clear the thumbnail pixmap cache."""
        self._thumb_cache.clear()
        if hasattr(_placeholder_thumb, "_cache"):
            del _placeholder_thumb._cache

    # ------------------------------------------------------------------
    # Helper to build item data
    # ------------------------------------------------------------------

    @staticmethod
    def build_item_data(clip: Any) -> dict[str, Any]:
        """Convert a Clip dataclass to a dict suitable for ``ItemDataRole.UserRole``.

        Args:
            clip: A ``moment.core.models.Clip`` instance.

        Returns:
            Dict with keys: id, stem, title, duration, game, file_size,
            status, favorite, thumb_path, encoded_path, r2_url, created_at.
        """
        return {
            "id": clip.id,
            "stem": clip.stem,
            "title": clip.title or clip.stem,
            "duration": clip.duration,
            "game": clip.game or "",
            "file_size": clip.file_size,
            "status": clip.status.name if hasattr(clip.status, "name") else str(clip.status),
            "favorite": clip.favorite,
            "thumb_path": str(clip.thumb_path) if clip.thumb_path else "",
            "encoded_path": str(clip.encoded_path) if clip.encoded_path else "",
            "r2_url": clip.r2_url or "",
            "edit_version": getattr(clip, "edit_version", 0),
            "accessible_description": (
                f"Clip: {clip.title or clip.stem}, "
                f"{_format_duration(clip.duration)}, "
                f"{clip.game or 'Unknown game'}"
                + (
                    f", {clip.created_at.strftime('%Y-%m-%d')}"
                    if isinstance(clip.created_at, datetime)
                    else ""
                )
            ),
            "created_at": (
                clip.created_at.isoformat()
                if isinstance(clip.created_at, datetime)
                else ""
            ),
        }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    """Format seconds as ``M:SS`` or ``H:MM:SS``."""
    total = int(max(seconds, 0))
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
