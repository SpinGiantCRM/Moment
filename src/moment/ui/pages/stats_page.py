"""Stats page — metrics dashboard with custom QPainter charts.

Layout (ui-revamp Phase 5)::

    ┌─────────────────────────────────────────────────────┐
    │  Dashboard                              [Refresh]   │
    ├──────────┬──────────┬──────────┬────────────────────┤
    │ [icon]   │ [icon]   │ [icon]   │ [icon]             │
    │ Clips    │ Time     │ Storage  │ Avg Duration       │
    ├──────────┴──────────┼──────────┴────────────────────┤
    │  Donut Chart        │  Bar Chart                    │
    │  (Top Games)        │  (Clips per Game)             │
    ├─────────────────────┴───────────────────────────────┤
    │  Table (Game Breakdown)                             │
    └─────────────────────────────────────────────────────┘

Metric cards use 24×24 accent-colored SVG icons. All charts are
custom QPainter implementations — no external charting dependency.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from moment.ui.services.async_loader import AsyncDataLoader

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_size(n_bytes: int) -> str:
    """Format a byte count into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}" if unit != "B" else f"{n_bytes} B"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


def _human_duration(secs: float) -> str:
    """Format seconds into H:MM:SS or M:SS."""
    if secs <= 0:
        return "—"
    total = int(secs)
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _human_duration_short(secs: float) -> str:
    """Format seconds into a compact 'Xm Ys' string."""
    if secs <= 0:
        return "—"
    total = int(secs)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60}s"
    h = total // 3600
    m = (total % 3600) // 60
    return f"{h}h {m}m"


def _parse_date(iso: str | None) -> str:
    """Format an ISO date string into ``YYYY-MM-DD`` or ``—``."""
    if iso is None:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso[:10] if len(iso) >= 10 else iso


# Chart colour palettes
_GAME_COLORS: list[QColor] = [
    QColor("#60a5fa"),  # blue
    QColor("#4ade80"),  # green
    QColor("#fb923c"),  # orange
    QColor("#f87171"),  # red
    QColor("#c084fc"),  # purple
    QColor("#fbbf24"),  # yellow
    QColor("#38bdf8"),  # sky
    QColor("#a78bfa"),  # violet
    QColor("#fb7185"),  # rose
    QColor("#34d399"),  # emerald
    QColor("#facc15"),  # amber
    QColor("#2dd4bf"),  # teal
]

# Metric card icon colour mapping
_METRIC_ICON_COLORS: dict[str, str] = {
    "clips": "#34d399",  # green
    "time": "#4a9eff",  # blue
    "storage": "#fbbf24",  # orange
    "avg": "#14b8a6",  # teal
}


# ---------------------------------------------------------------------------
# Metric Card
# ---------------------------------------------------------------------------


class _MetricCard(QFrame):
    """A single metric display card — accent-colored icon, value, label."""

    def __init__(
        self,
        icon_name: str,
        label: str,
        color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setStyleSheet("""
            QFrame#metricCard {
                background-color: #242424;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
            }
        """)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(8)

        # Top row: icon + label
        top = QHBoxLayout()
        top.setSpacing(10)
        top.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 24×24 colored icon
        from moment.ui.resources import load_icon

        icon_lbl = QLabel()
        icon = load_icon(icon_name, color)
        if not icon.isNull():
            icon_lbl.setPixmap(icon.pixmap(24, 24))
        top.addWidget(icon_lbl)

        self._label = QLabel(label)
        self._label.setStyleSheet(
            "font-size: 12px; color: var(--text-secondary); background: transparent;"
        )
        top.addWidget(self._label)
        top.addStretch()
        layout.addLayout(top)

        # Value
        self._value = QLabel("—")
        self._value.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: var(--text-primary);background: transparent;"
        )
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


# ---------------------------------------------------------------------------
# Donut Chart
# ---------------------------------------------------------------------------


class _DonutChart(QWidget):
    """Custom QPainter donut chart with hover expand, gaps, and legend."""

    _ARC_GAP = 2  # degrees gap between segments
    _HOVER_EXPAND = 2  # px expansion on hover
    _HOLE_PCT = 0.40  # center hole as fraction of radius
    _HOVER_BRIGHTEN = 1.20  # multiplier on hover

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._data: list[dict] = []
        self._segments: list[dict] = []  # computed arc info
        self._hovered_seg: int = -1
        self._total_count: int = 0
        self._legend: list[tuple[str, str, QColor]] = []

    def set_data(self, clips_per_game: list[dict]) -> None:
        """Accept list of ``{game, count, storage}`` dicts."""
        self._data = clips_per_game
        self._total_count = sum(d.get("count", 0) for d in clips_per_game)
        self._segments = self._compute_segments()
        self._legend = self._build_legend()
        self.update()

    def _compute_segments(self) -> list[dict]:
        """Compute arc segment data: start_angle, span, color, label, value."""
        if not self._data:
            return []

        total = sum(d.get("storage", 0) for d in self._data)
        if total == 0:
            return []

        segments: list[dict] = []
        current = 90.0  # start from top (12 o'clock)
        n = min(len(self._data), len(_GAME_COLORS))
        gap_deg = self._ARC_GAP

        for i in range(n):
            d = self._data[i]
            storage = d.get("storage", 0)
            fraction = storage / total if total > 0 else 0
            span = fraction * 360.0
            if span <= 0:
                continue
            segments.append(
                {
                    "start": current,
                    "span": span,
                    "color": _GAME_COLORS[i],
                    "label": d.get("game", ""),
                    "value": _human_size(storage),
                    "count": d.get("count", 0),
                }
            )
            current += span + gap_deg

        return segments

    def _build_legend(self) -> list[tuple[str, str, QColor]]:
        """Build legend entries: (label, value, color)."""
        # Show all segments (cap at 8 for legend size)
        return [(s["label"], s["value"], s["color"]) for s in self._segments[:8]]

    def _arc_angles_1_16th(self) -> list[tuple[float, float, QColor]]:
        """Return list of ``(start, span, color)`` in 1/16 degree units."""
        return [(s["start"] * 16, s["span"] * 16, s["color"]) for s in self._segments]

    # ── Hover detection ──────────────────────────────────────────────

    def _segment_at(self, pos: QPoint) -> int:
        """Return segment index under the mouse, or -1."""
        if not self._segments:
            return -1
        cx = self.width() / 2
        cy = self._chart_center_y()
        dx = pos.x() - cx
        dy = pos.y() - cy

        # Distance from center
        outer_r = self._chart_radius()
        inner_r = outer_r * self._HOLE_PCT
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < inner_r or dist > outer_r + self._HOVER_EXPAND:
            return -1

        # Angle (from top, clockwise, in degrees)
        angle = (90 - self._angle_deg(dx, dy)) % 360

        for i, seg in enumerate(self._segments):
            start = seg["start"] % 360
            end = (start + seg["span"]) % 360
            if start <= end:
                if start <= angle <= end:
                    return i
            else:  # wraps around 360
                if angle >= start or angle <= end:
                    return i
        return -1

    @staticmethod
    def _angle_deg(dx: float, dy: float) -> float:
        """Compute angle in degrees from positive X axis."""
        return math.degrees(math.atan2(dy, dx))

    def _chart_radius(self) -> float:
        """Outer radius of the donut."""
        w, h = self.width(), self.height()
        return min(w, h) / 2 - 16

    def _chart_center_y(self) -> float:
        """Y center of the chart (offset for legend below)."""
        return self.height() / 2 - 10

    # ── Mouse events ─────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        old = self._hovered_seg
        self._hovered_seg = self._segment_at(event.pos())
        if old != self._hovered_seg:
            self.update()
            if self._hovered_seg >= 0:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()

    def leaveEvent(self, event) -> None:
        self._hovered_seg = -1
        self.unsetCursor()
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self._chart_center_y()
        outer_r = self._chart_radius()
        inner_r = outer_r * self._HOLE_PCT

        outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
        inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

        angles = self._arc_angles_1_16th()

        if not angles:
            # Empty state — gray ring
            p.setPen(QPen(QColor("#3a3a3a"), 6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(outer_rect.adjusted(3, 3, -3, -3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2a2a2a"))
            p.drawEllipse(inner_rect)
        else:
            # Draw segments with hover expansion
            gap_pen = QPen(QColor("#2a2a2a"), self._ARC_GAP)

            for i, (start, span, color) in enumerate(angles):
                is_hovered = i == self._hovered_seg
                expand = self._HOVER_EXPAND if is_hovered else 0
                seg_rect = outer_rect.adjusted(-expand, -expand, expand, expand)
                # Brighten on hover
                seg_color = QColor(color)
                if is_hovered:
                    seg_color = seg_color.lighter(int(self._HOVER_BRIGHTEN * 100))

                p.setPen(gap_pen)
                p.setBrush(seg_color)
                p.drawPie(seg_rect, int(start), int(span))

            # Inner cutout
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2a2a2a"))
            p.drawEllipse(inner_rect)

        # ── Center text ─────────────────────────────────────────────
        if self._total_count > 0:
            p.setPen(QColor("#ffffff"))
            font = QFont()
            font.setPointSize(16)
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            center_rect = QRectF(
                inner_rect.left(),
                inner_rect.top() + inner_rect.height() * 0.32,
                inner_rect.width(),
                22,
            )
            p.drawText(center_rect, Qt.AlignmentFlag.AlignCenter, str(self._total_count))

            p.setPen(QColor("#a1a1aa"))
            font2 = QFont()
            font2.setPointSize(9)
            p.setFont(font2)
            sub_rect = QRectF(
                inner_rect.left(),
                center_rect.bottom() + 1,
                inner_rect.width(),
                16,
            )
            p.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, "total clips")

        # ── Legend below chart ──────────────────────────────────────
        legend_y = int(cy + outer_r + 12)
        legend_x = int(cx - 80)
        fm = QFontMetrics(QFont())
        font3 = QFont()
        font3.setPointSize(10)
        p.setFont(font3)

        for label, value, color in self._legend:
            # Color dot (8px diameter)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            dot_rect = QRect(int(legend_x), legend_y, 8, 8)
            p.drawRoundedRect(QRectF(dot_rect), 2, 2)

            # Label
            p.setPen(QColor("#d9d9d9"))
            label_text = fm.elidedText(label, Qt.TextElideMode.ElideRight, 90)
            p.drawText(
                QRect(legend_x + 14, legend_y - 1, 90, 16),
                Qt.AlignmentFlag.AlignLeft,
                label_text,
            )

            # Value
            p.setPen(QColor("#a1a1aa"))
            val_rect = QRect(legend_x + 104, legend_y - 1, 56, 16)
            p.drawText(val_rect, Qt.AlignmentFlag.AlignRight, value)

            legend_y += 18

        p.end()


# ---------------------------------------------------------------------------
# Bar Chart
# ---------------------------------------------------------------------------


class _BarChart(QWidget):
    """Custom QPainter bar chart — vertical bars with gradient fill, dashed
    gridlines, and hover QToolTip."""

    _BAR_RADIUS = 3  # top corner radius
    _MIN_BAR_W = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._data: list[dict] = []
        self._hovered_idx: int = -1
        # Title drawn above bars

    def set_data(self, data: list[dict]) -> None:
        """Accept list of ``{game, count}`` or ``{date, count}`` dicts."""
        self._data = data
        self.update()

    # ── Mouse events ─────────────────────────────────────────────────

    def _bar_at(self, x: int) -> int:
        """Return bar index under x-coordinate, or -1."""
        if not self._data:
            return -1
        margin_l, margin_r = 40, 12
        bar_w = max(self._MIN_BAR_W, (self.width() - margin_l - margin_r) / len(self._data) - 2)
        idx = int((x - margin_l) / (bar_w + 2))
        if 0 <= idx < len(self._data):
            return idx
        return -1

    def mouseMoveEvent(self, event) -> None:
        old = self._hovered_idx
        self._hovered_idx = self._bar_at(int(event.position().x()))
        if old != self._hovered_idx:
            self.update()
            if self._hovered_idx >= 0 and self._hovered_idx < len(self._data):
                d = self._data[self._hovered_idx]
                label = d.get("game") or d.get("date", "")
                count = d.get("count", 0)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{label}: {count}",
                    self,
                )
            else:
                QToolTip.hideText()

    def leaveEvent(self, event) -> None:
        self._hovered_idx = -1
        QToolTip.hideText()
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin_l, margin_r, margin_b, margin_t = 40, 12, 28, 28

        if not self._data:
            p.setPen(QColor("#a1a1aa"))
            font = QFont()
            font.setPointSize(11)
            p.setFont(font)
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No data yet")
            p.end()
            return

        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b
        max_val = max(d.get("count", 0) for d in self._data) if self._data else 1
        max_val = max(max_val, 1)
        n = len(self._data)
        bar_w = max(self._MIN_BAR_W, chart_w / n - 2)
        bar_spacing = 2

        # ── Dashed Y-axis gridlines ──────────────────────────────────
        dash_pen = QPen(QColor("#3d3d3d"), 1, Qt.PenStyle.DashLine)
        dash_pen.setDashPattern([4, 6])

        for level_pct in (25, 50, 75, 100):
            y = margin_t + int(chart_h * (1 - level_pct / 100))
            p.setPen(dash_pen)
            p.drawLine(margin_l, y, w - margin_r, y)

            # Y-axis label
            level_val = int(max_val * level_pct / 100)
            p.setPen(QColor("#8a8a8a"))
            font9 = QFont()
            font9.setPointSize(9)
            p.setFont(font9)
            label_rect = QRect(0, y - 8, margin_l - 4, 16)
            p.drawText(label_rect, Qt.AlignmentFlag.AlignRight, str(level_val))

        # ── Bars ─────────────────────────────────────────────────────
        base_color = QColor("#60a5fa")
        hover_border_color = QColor("#93c5fd")

        for i, d in enumerate(self._data):
            count = d.get("count", 0)
            is_hovered = i == self._hovered_idx
            bar_h_val = (count / max_val) * chart_h if max_val > 0 else 0
            bar_h_val = max(bar_h_val, 1)  # minimum 1px bar
            # Clamp corner radius to half bar height for very short bars
            bar_radius = min(self._BAR_RADIUS, bar_h_val / 2)

            x = margin_l + i * (bar_w + bar_spacing)
            y = margin_t + chart_h - bar_h_val

            # Gradient fill: +30% brightness top → base color bottom
            gradient = QLinearGradient(
                QPointF(x, y),
                QPointF(x, y + bar_h_val),
            )
            top_color = base_color.lighter(130)
            gradient.setColorAt(0.0, top_color)
            gradient.setColorAt(1.0, base_color)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gradient)
            bar_rect = QRectF(float(x), float(y), float(bar_w), float(bar_h_val))
            p.drawRoundedRect(bar_rect, bar_radius, bar_radius)

            # Hover: bright border
            if is_hovered:
                p.setPen(QPen(hover_border_color, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(bar_rect, bar_radius, bar_radius)

        # ── X-axis labels ────────────────────────────────────────────
        p.setPen(QColor("#a1a1aa"))
        font8 = QFont()
        font8.setPointSize(8)
        p.setFont(font8)

        rotate = n > 6

        for i, d in enumerate(self._data):
            label = d.get("game") or d.get("date", "")[:12]
            x_center = margin_l + i * (bar_w + bar_spacing) + bar_w / 2
            y_label = h - margin_b + 14

            if rotate:
                p.save()
                p.translate(x_center, y_label)
                p.rotate(30)
                # Truncate label
                fm = QFontMetrics(p.font())
                text = fm.elidedText(label, Qt.TextElideMode.ElideRight, 60)
                p.drawText(QRect(0, -6, 60, 16), Qt.AlignmentFlag.AlignLeft, text)
                p.restore()
            else:
                fm = QFontMetrics(p.font())
                text_w = int(bar_w + bar_spacing + 2)
                text = fm.elidedText(label, Qt.TextElideMode.ElideRight, text_w)
                p.drawText(
                    QRectF(
                        x_center - (bar_w + bar_spacing) / 2, y_label - 2, bar_w + bar_spacing, 16
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )

        p.end()


# ---------------------------------------------------------------------------
# Stats Page
# ---------------------------------------------------------------------------


class StatsPage(QWidget):
    """Dashboard page with metric cards, donut/bar charts, and game breakdown table."""

    clip_activated = pyqtSignal(str)

    def __init__(self, store: "Store | None" = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(12)

        # ── Title row + Refresh ───────────────────────────────────────────
        title_row = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        content_layout.addLayout(title_row)

        # ── Metric cards (4 across) ───────────────────────────────────────
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)

        self._card_clips = _MetricCard(
            "library",
            "Total Clips",
            _METRIC_ICON_COLORS["clips"],
        )
        self._card_time = _MetricCard(
            "player",
            "Total Time",
            _METRIC_ICON_COLORS["time"],
        )
        self._card_storage = _MetricCard(
            "stats",
            "Storage Used",
            _METRIC_ICON_COLORS["storage"],
        )
        self._card_avg = _MetricCard(
            "record",
            "Avg Duration",
            _METRIC_ICON_COLORS["avg"],
        )

        metrics_row.addWidget(self._card_clips)
        metrics_row.addWidget(self._card_time)
        metrics_row.addWidget(self._card_storage)
        metrics_row.addWidget(self._card_avg)
        content_layout.addLayout(metrics_row)

        # ── Charts row ────────────────────────────────────────────────────
        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        # Donut chart card
        donut_card = QFrame()
        donut_card.setObjectName("chartCard")
        donut_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: #242424;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
            }
        """)
        donut_layout = QVBoxLayout(donut_card)
        donut_layout.setContentsMargins(12, 10, 12, 10)
        donut_layout.setSpacing(6)
        donut_title = QLabel("Top Games by Storage")
        donut_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: var(--text-primary);background: transparent;"
        )
        donut_layout.addWidget(donut_title)
        self._donut_chart = _DonutChart()
        donut_layout.addWidget(self._donut_chart, stretch=1)
        charts_row.addWidget(donut_card, stretch=1)

        # Bar chart card
        bar_card = QFrame()
        bar_card.setObjectName("chartCard")
        bar_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: #242424;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
            }
        """)
        bar_layout = QVBoxLayout(bar_card)
        bar_layout.setContentsMargins(12, 10, 12, 10)
        bar_layout.setSpacing(6)
        bar_title = QLabel("Clips per Game")
        bar_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: var(--text-primary);background: transparent;"
        )
        bar_layout.addWidget(bar_title)
        self._bar_chart = _BarChart()
        bar_layout.addWidget(self._bar_chart, stretch=1)
        charts_row.addWidget(bar_card, stretch=2)

        content_layout.addLayout(charts_row, stretch=1)

        # ── Game breakdown table ──────────────────────────────────────────
        table_card = QFrame()
        table_card.setObjectName("chartCard")
        table_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: #242424;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
            }
        """)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 10, 12, 10)
        table_layout.setSpacing(6)
        tbl_title = QLabel("Game Breakdown")
        tbl_title.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: var(--text-primary);background: transparent;"
        )
        table_layout.addWidget(tbl_title)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            [
                "Game",
                "Clips",
                "Total Time",
                "Avg Duration",
                "Storage",
            ]
        )
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
                color: var(--text-secondary);
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background-color: #323232;
                color: var(--text-primary);
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #a0a0a0;
                border: none;
                border-bottom: 1px solid #3d3d3d;
                padding: 6px 8px;
                font-weight: 600;
                font-size: 12px;
            }
            QTableWidget {
                alternate-background-color: #1e1e1e;
            }
        """)
        self._table.cellClicked.connect(self._on_table_cell_clicked)
        table_layout.addWidget(self._table)
        content_layout.addWidget(table_card)

        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # Async loader
        self._loader: AsyncDataLoader | None = None

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Load aggregate stats from the store asynchronously."""
        if self._store is None:
            self._show_zero_state()
            return

        self._cancel_loader()

        # Show loading placeholders
        self._card_clips.set_value("…")
        self._card_time.set_value("…")
        self._card_storage.set_value("…")
        self._card_avg.set_value("…")
        self._refresh_btn.setEnabled(False)

        self._loader = AsyncDataLoader(self._store.get_aggregate_stats)
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_load_error)
        self._loader.start()

    def _on_data_ready(self, stats: dict) -> None:
        """Handle successful async stats load."""
        self._loader = None
        self._refresh_btn.setEnabled(True)

        # Compute derived metrics
        total_clips = stats.get("total_clips", 0)
        total_storage = stats.get("total_storage_bytes", 0)
        games = stats.get("clips_per_game", [])

        # Total time: sum from game data if available
        total_time_s = 0.0
        for g in games:
            dur = g.get("total_duration", g.get("duration", 0))
            total_time_s += float(dur) if dur else 0.0

        avg_duration_s = total_time_s / total_clips if total_clips > 0 else 0.0

        self._card_clips.set_value(str(total_clips))
        self._card_time.set_value(_human_duration(total_time_s) if total_time_s > 0 else "—")
        self._card_storage.set_value(_human_size(total_storage))
        self._card_avg.set_value(
            _human_duration_short(avg_duration_s) if avg_duration_s > 0 else "—"
        )

        self._donut_chart.set_data(games)
        self._bar_chart.set_data(games)
        self._populate_table(games)

    def _on_load_error(self, error: str) -> None:
        """Handle async load failure."""
        self._loader = None
        self._refresh_btn.setEnabled(True)
        logger.exception("Failed to load stats: %s", error)
        self._card_clips.set_value("Error")
        self._card_time.set_value("Retry")
        self._card_storage.set_value("—")
        self._card_avg.set_value("—")
        self._donut_chart.set_data([])
        self._bar_chart.set_data([])
        self._table.setRowCount(0)

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

    # ==================================================================
    # Internals
    # ==================================================================

    def _show_zero_state(self) -> None:
        """Show zeros / empty state across all widgets."""
        self._card_clips.set_value("0")
        self._card_time.set_value("—")
        self._card_storage.set_value("0 B")
        self._card_avg.set_value("—")
        self._donut_chart.set_data([])
        self._bar_chart.set_data([])
        self._table.setRowCount(0)

    def _populate_table(self, games: list[dict]) -> None:
        """Fill the game breakdown table."""
        self._table.setRowCount(len(games))
        for i, g in enumerate(games):
            game = g.get("game", "—")
            count = str(g.get("count", 0))
            dur = float(g.get("total_duration", g.get("duration", 0)) or 0)
            avg_s = dur / float(g.get("count", 1)) if g.get("count") else 0
            storage = _human_size(g.get("storage", 0))

            self._table.setItem(i, 0, QTableWidgetItem(game))
            self._table.setItem(i, 1, QTableWidgetItem(count))
            self._table.setItem(i, 2, QTableWidgetItem(_human_duration(dur) if dur > 0 else "—"))
            self._table.setItem(
                i, 3, QTableWidgetItem(_human_duration_short(avg_s) if avg_s > 0 else "—")
            )
            self._table.setItem(i, 4, QTableWidgetItem(storage))

            # Store clip ID for navigation if available
            clip_id = g.get("id", "")
            if clip_id:
                self._table.item(i, 0).setData(Qt.ItemDataRole.UserRole, clip_id)

    def _on_table_cell_clicked(self, row: int, col: int) -> None:
        """Navigate to player when a row is clicked and has a clip ID."""
        item = self._table.item(row, 0)
        if item is None:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        if clip_id:
            self.clip_activated.emit(clip_id)
