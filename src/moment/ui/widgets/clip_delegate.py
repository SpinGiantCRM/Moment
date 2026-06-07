"""Clip delegate — custom-painted grid card for Clip items with 3 card sizes.

Renders clip cards at small (200×136), medium (272×176), or large (360×224)
with 16:9 thumbnail, skeleton shimmer animation, duration badge, hover heart
icon, and a clean metadata row.  Card sizes are toggled via the class-level
``_card_size`` variable and ``set_card_size()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QModelIndex, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

# ---------------------------------------------------------------------------
# Layout constants — 3 card sizes
# ---------------------------------------------------------------------------

_CARD_SIZES: dict[int, dict[str, int]] = {
    0: {"card_w": 200, "card_h": 136, "thumb_w": 184, "thumb_h": 104, "meta_h": 32},
    1: {"card_w": 272, "card_h": 176, "thumb_w": 256, "thumb_h": 144, "meta_h": 32},
    2: {"card_w": 360, "card_h": 224, "thumb_w": 344, "thumb_h": 176, "meta_h": 48},
}

_RADIUS = 6
_THUMB_TOP_RADIUS = 4
_PADDING = 8

# ── Colours (from design system) ────────────────────────────────────────────
BG_NORMAL = QColor("#363636")
BG_ELEVATED = QColor("#333333")
BORDER_SUBTLE = QColor("#454545")
BORDER_HOVER = QColor("#505050")
BORDER_FOCUS = QColor("#4a9eff")
TEXT_PRIMARY = QColor("#f0f0f0")
TEXT_SECONDARY = QColor("#b8b8b8")
OVERLAY_BADGE = QColor(0, 0, 0, 200)
HEART_INACTIVE = QColor("#505050")
HEART_ACTIVE = QColor("#f87171")
SKELETON_BASE = QColor("#2e2e2e")
SKELETON_SHINE = QColor("#333333")


# ── Skeleton shimmer animation (shared across all delegates) ────────────────
# A class-level timer drives a single 1.5s cycle; each card's paint offsets
# the shimmer based on its row so cards don't pulse in lockstep.

_shimmer_offset: float = 0.0
_shimmer_timer: QTimer | None = None
_shimmer_views: list[QWidget] = []  # list views to repaint on each tick


def _start_shimmer_timer() -> None:
    """Start the shared shimmer animation timer (16ms / ~60 fps)."""
    global _shimmer_timer
    if _shimmer_timer is None:
        _shimmer_timer = QTimer()
        _shimmer_timer.setInterval(16)
        _shimmer_timer.timeout.connect(_tick_shimmer)
        _shimmer_timer.start()


def _tick_shimmer() -> None:
    """Advance the global shimmer offset by one frame and repaint all views."""
    global _shimmer_offset, _shimmer_views
    _shimmer_offset = (_shimmer_offset + 16 / 1500) % 1.0
    alive: list[QWidget] = []
    for view in _shimmer_views:
        if view is None:
            continue
        try:
            if view.isVisible():
                view.viewport().update()
            alive.append(view)
        except RuntimeError:
            # View was deleted — drop stale reference so the timer stays safe.
            continue
    _shimmer_views = alive


# ===========================================================================
# Delegate
# ===========================================================================


class ClipDelegate(QStyledItemDelegate):
    """Custom painter delegate for clip grid cards (IconMode).

    Supports 3 card sizes toggled at the class level via
    :meth:`set_card_size`.  Thumbnails without loaded images display a
    skeleton shimmer animation.
    """

    _card_size: int = 1  # 0=small, 1=medium, 2=large

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumb_cache: dict[tuple[str, str], QPixmap] = {}
        _start_shimmer_timer()

    # ------------------------------------------------------------------
    # Class-level card size
    # ------------------------------------------------------------------

    @classmethod
    def set_card_size(cls, size: int) -> None:
        """Set the card size for ALL ClipDelegate instances.

        Args:
            size: 0 = small (200×136), 1 = medium (272×176), 2 = large (360×224).
        """
        cls._card_size = max(0, min(2, size))

    @classmethod
    def card_size(cls) -> int:
        """Return the current card size index (0/1/2)."""
        return cls._card_size

    @staticmethod
    def register_shimmer_view(view: QWidget) -> None:
        """Register a QListView to be repainted on each shimmer tick.

        Call this from the grid page after creating the list view so the
        skeleton shimmer animation actually renders.
        """
        global _shimmer_views
        if view not in _shimmer_views:
            _shimmer_views.append(view)
            _start_shimmer_timer()

    @staticmethod
    def unregister_shimmer_view(view: QWidget) -> None:
        """Remove a previously registered shimmer view."""
        global _shimmer_views
        if view in _shimmer_views:
            _shimmer_views.remove(view)

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def _layout(self) -> dict[str, int]:
        """Return the layout dict for the current card size."""
        return _CARD_SIZES[self._card_size]

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        lo = self._layout()
        return QSize(lo["card_w"], lo["card_h"])

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        lo = self._layout()
        card_w = lo["card_w"]
        thumb_w = lo["thumb_w"]
        thumb_h = lo["thumb_h"]

        # --- State ---
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        card_rect = QRectF(option.rect).adjusted(2, 2, -2, -2)

        # --- Card background ---
        if selected:
            pen = QPen(BORDER_FOCUS, 2)
            bg = BG_NORMAL
        elif hovered:
            pen = QPen(BORDER_HOVER, 1)
            bg = BG_NORMAL
        else:
            pen = QPen(BORDER_SUBTLE, 1)
            bg = BG_NORMAL

        painter.setPen(pen)
        painter.setBrush(bg)
        painter.drawRoundedRect(card_rect, _RADIUS, _RADIUS)

        # --- Data ---
        data = index.data(Qt.ItemDataRole.UserRole)
        if data is None:
            painter.restore()
            return

        title = data.get("title") or data.get("stem", "Untitled")
        duration = data.get("duration", 0.0)
        game = data.get("game") or ""
        favorite = data.get("favorite", False)
        thumb_path = data.get("thumb_path", "")
        clip_id = data.get("id", "")
        created_at = data.get("created_at", "")

        # ── Thumbnail area ─────────────────────────────────────────────
        thumb_x = option.rect.x() + (card_w - thumb_w) // 2
        thumb_y = option.rect.y() + _PADDING
        thumb_rect = QRectF(thumb_x, thumb_y, thumb_w, thumb_h)

        painter.save()
        clip_path = QPainterPath()
        # Top corners: 4px radius, bottom corners: 2px radius
        clip_path.addRoundedRect(thumb_rect, _THUMB_TOP_RADIUS, _THUMB_TOP_RADIUS)
        painter.setClipPath(clip_path)

        pixmap = self._get_thumbnail(clip_id, thumb_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                thumb_w,
                thumb_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            src_x = max(0, (scaled.width() - thumb_w) // 2)
            src_y = max(0, (scaled.height() - thumb_h) // 2)
            painter.drawPixmap(
                int(thumb_rect.x()),
                int(thumb_rect.y()),
                scaled,
                src_x,
                src_y,
                thumb_w,
                thumb_h,
            )
        else:
            # Skeleton shimmer placeholder
            self._draw_skeleton_thumb(painter, thumb_rect, index.row())

        painter.restore()

        # ── Duration badge (bottom-right of thumbnail) ─────────────────
        if duration > 0:
            self._draw_duration_badge(painter, thumb_rect, duration)

        # ── Heart icon (top-right on hover, or always if favorited) ────
        if hovered or favorite:
            self._draw_heart(painter, card_rect, thumb_rect, favorite, hovered)

        # ── Metadata row ───────────────────────────────────────────────
        meta_y = thumb_y + thumb_h + 4
        meta_width = thumb_w

        # Title
        painter.setPen(TEXT_PRIMARY)
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)

        title_rect = QRectF(thumb_x + 4, meta_y, meta_width - 8, 14)
        elided = painter.fontMetrics().elidedText(
            title,
            Qt.TextElideMode.ElideRight,
            int(title_rect.width()),
        )
        painter.drawText(
            title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided
        )

        # Subtitle: date · game · duration
        meta2_y = meta_y + 14
        painter.setPen(TEXT_SECONDARY)
        font2 = painter.font()
        font2.setPointSize(9)
        font2.setBold(False)
        painter.setFont(font2)

        parts: list[str] = []
        # Format date
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                parts.append(dt.strftime("%b %d"))
            except (ValueError, TypeError):
                pass
        if game:
            parts.append(game)
        if duration > 0:
            parts.append(_format_duration(duration))

        meta_text = " · ".join(parts) if parts else ""
        meta2_rect = QRectF(thumb_x + 4, meta2_y, meta_width - 8, 14)
        elided_meta = painter.fontMetrics().elidedText(
            meta_text,
            Qt.TextElideMode.ElideRight,
            int(meta2_rect.width()),
        )
        painter.drawText(
            meta2_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_meta,
        )

        # Large card: second metadata line (file size + resolution)
        if self._card_size == 2:
            meta3_y = meta2_y + 14
            file_size = data.get("file_size", 0)
            resolution = data.get("resolution", (0, 0))
            res_str = ""
            if isinstance(resolution, (tuple, list)) and len(resolution) == 2:
                w, h = resolution
                if w > 0 and h > 0:
                    res_str = f"{w}×{h}"
            size_str = _format_size(file_size) if file_size else ""
            extra = " · ".join(p for p in [size_str, res_str] if p)
            if extra:
                meta3_rect = QRectF(thumb_x + 4, meta3_y, meta_width - 8, 14)
                elided_extra = painter.fontMetrics().elidedText(
                    extra,
                    Qt.TextElideMode.ElideRight,
                    int(meta3_rect.width()),
                )
                painter.drawText(
                    meta3_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    elided_extra,
                )

        painter.restore()

    # ------------------------------------------------------------------
    # Skeleton shimmer thumbnail
    # ------------------------------------------------------------------

    def _draw_skeleton_thumb(
        self,
        painter: QPainter,
        rect: QRectF,
        row: int,
    ) -> None:
        """Draw a skeleton shimmer placeholder in the thumbnail area."""
        global _shimmer_offset

        # Base fill
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SKELETON_BASE)
        painter.drawRect(rect)

        # Shimmer band — offset by row so cards don't pulse in unison
        band_width = 60
        row_phase = (row * 0.15) % 1.0
        local_phase = (_shimmer_offset + row_phase) % 1.0
        band_x = rect.x() + local_phase * (rect.width() + band_width) - band_width

        if band_x < rect.right() and band_x + band_width > rect.x():
            painter.setBrush(SKELETON_SHINE)
            band_rect = QRectF(
                max(rect.x(), band_x),
                rect.y(),
                min(rect.width(), band_width),
                rect.height(),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(band_rect)

    # ------------------------------------------------------------------
    # Duration badge
    # ------------------------------------------------------------------

    def _draw_duration_badge(
        self,
        painter: QPainter,
        thumb_rect: QRectF,
        duration: float,
    ) -> None:
        badge_text = _format_duration(duration)
        font = painter.font()
        font.setFamily("JetBrains Mono, SF Mono, Consolas, monospace")
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        text_w = fm.horizontalAdvance(badge_text) + 8
        text_h = fm.height() + 2
        badge_x = thumb_rect.right() - text_w - 4
        badge_y = thumb_rect.bottom() - text_h - 4
        badge_rect = QRectF(badge_x, badge_y, text_w, text_h)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(OVERLAY_BADGE)
        painter.drawRoundedRect(badge_rect, 3, 3)

        painter.setPen(QColor("#ffffff"))
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

    # ------------------------------------------------------------------
    # Heart icon
    # ------------------------------------------------------------------

    def _draw_heart(
        self,
        painter: QPainter,
        card_rect: QRectF,
        thumb_rect: QRectF,
        favorite: bool,
        hovered: bool,
    ) -> None:
        """Draw a heart icon (18×18) at top-right of the card."""
        heart_size = 18
        heart_x = card_rect.right() - heart_size - 6
        heart_y = card_rect.top() + 6

        from moment.ui.resources import load_icon

        if favorite:
            icon = load_icon("heart-filled", HEART_ACTIVE.name(), size=heart_size)
        else:
            icon = load_icon("heart", HEART_INACTIVE.name(), size=heart_size)

        pixmap = icon.pixmap(heart_size, heart_size)
        painter.drawPixmap(int(heart_x), int(heart_y), pixmap)

    # ------------------------------------------------------------------
    # Thumbnail cache
    # ------------------------------------------------------------------

    def _get_thumbnail(self, clip_id: str, thumb_path: str) -> QPixmap:
        cache_key = (clip_id, thumb_path)
        cached = self._thumb_cache.get(cache_key)
        if cached is not None:
            return cached

        if thumb_path:
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                self._thumb_cache[cache_key] = pixmap
                if len(self._thumb_cache) > 250:
                    oldest = next(iter(self._thumb_cache))
                    del self._thumb_cache[oldest]
                return pixmap

        empty = QPixmap()
        self._thumb_cache[cache_key] = empty
        return empty

    def clear_thumb_cache(self) -> None:
        self._thumb_cache.clear()

    # ------------------------------------------------------------------
    # Build item data (static helper)
    # ------------------------------------------------------------------

    @staticmethod
    def build_item_data(clip: Any) -> dict[str, Any]:
        """Convert a Clip dataclass to a dict for ``ItemDataRole.UserRole``."""
        return {
            "id": clip.id,
            "stem": clip.stem,
            "title": clip.title or clip.stem,
            "duration": clip.duration,
            "game": clip.game or "",
            "file_size": clip.file_size,
            "status": clip.status.name if hasattr(clip.status, "name") else str(clip.status),
            "favorite": clip.favorite,
            "protect_from_retention": clip.protect_from_retention,
            "thumb_path": str(clip.thumb_path) if clip.thumb_path else "",
            "encoded_path": str(clip.encoded_path) if clip.encoded_path else "",
            "source_path": str(clip.source_path),
            "r2_url": clip.r2_url or "",
            "edit_version": getattr(clip, "edit_version", 0),
            "resolution": clip.resolution if hasattr(clip, "resolution") else (0, 0),
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
                clip.created_at.isoformat() if isinstance(clip.created_at, datetime) else ""
            ),
            "recorded_at": (
                clip.recorded_at.isoformat()
                if isinstance(getattr(clip, "recorded_at", None), datetime)
                else ""
            ),
            "tags": list(getattr(clip, "tags", []) or []),
        }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    total = int(max(seconds, 0))
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.0f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
