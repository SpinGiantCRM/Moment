"""Stats page — metrics dashboard with custom QPainter charts.

Displays aggregate clip statistics: total clips, storage used,
uploads today/this week, a donut chart of top games by storage,
a bar chart of captures per day (30 days), and a recent uploads table.

All charts are custom-widget QPainter implementations — no external
charting library dependency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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


def _parse_date(iso: str | None) -> str:
    """Format an ISO date string into ``YYYY-MM-DD`` or ``—``."""
    if iso is None:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso[:10] if len(iso) >= 10 else iso


# Game-palette colours for donut slices
_GAME_COLORS: list[QColor] = [
    QColor("#60a5fa"),  # blue
    QColor("#4ade80"),  # green
    QColor("#fb923c"),  # orange
    QColor("#f87171"),  # red
    QColor("#c084fc"),  # purple
    QColor("#fbbf24"),  # yellow
]


# ---------------------------------------------------------------------------
# Metric Card
# ---------------------------------------------------------------------------


class _MetricCard(QFrame):
    """A single metric display card — icon, label, value."""

    def __init__(self, icon: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setStyleSheet("""
            QFrame#metricCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        self.setMinimumHeight(72)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 20px;")
        top.addWidget(icon_lbl)

        self._label = QLabel(label)
        self._label.setObjectName("cardMeta")
        top.addWidget(self._label)
        top.addStretch()
        layout.addLayout(top)

        self._value = QLabel("—")
        self._value.setObjectName("pageTitle")
        self._value.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


# ---------------------------------------------------------------------------
# Donut Chart
# ---------------------------------------------------------------------------


class _DonutChart(QWidget):
    """Custom QPainter donut chart — top 5 games by storage + "Other"."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._data: list[dict] = []
        self._legend: list[tuple[str, str, QColor]] = []

    def set_data(self, clips_per_game: list[dict]) -> None:
        """Accept list of ``{game, count, storage}`` dicts."""
        self._data = clips_per_game
        self._legend = self._build_legend()
        self.update()

    def _build_legend(self) -> list[tuple[str, str, QColor]]:
        """Build legend entries: (label, value, color)."""
        if not self._data:
            return []

        # Top 5 + "Other"
        top5 = self._data[:5]
        other_count = sum(d["count"] for d in self._data[5:])
        other_storage = sum(d["storage"] for d in self._data[5:])

        legend: list[tuple[str, str, QColor]] = []
        for i, d in enumerate(top5):
            color = _GAME_COLORS[i % len(_GAME_COLORS)]
            legend.append((d["game"], _human_size(d["storage"]), color))

        if other_count > 0:
            legend.append(("Other", _human_size(other_storage), QColor("#555555")))

        return legend

    def _arc_angles(self) -> list[tuple[float, float, QColor]]:
        """Return list of ``(start_angle, span_angle, color)`` in 1/16deg units."""
        if not self._legend:
            return []

        total = sum(self._data[i]["storage"] for i in range(min(5, len(self._data))))
        if len(self._data) > 5:
            total += sum(d["storage"] for d in self._data[5:])

        if total == 0:
            return [(0, 360 * 16, QColor("#3a3a3a"))]

        angles: list[tuple[float, float, QColor]] = []
        current = 90 * 16  # Start from top
        for i, d in enumerate(self._data[:5]):
            storage = d["storage"]
            span = (storage / total) * 360 * 16
            color = _GAME_COLORS[i % len(_GAME_COLORS)]
            angles.append((current, span, color))
            current += span

        # "Other"
        other_storage = sum(d["storage"] for d in self._data[5:])
        if other_storage > 0:
            span = (other_storage / total) * 360 * 16
            angles.append((current, span, QColor("#555555")))
            current += span

        return angles

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        # Chart area (left side)
        chart_size = min(w - 140, h) - 16
        chart_x = 8
        chart_y = (h - chart_size) // 2

        # Inner radius
        inner_pct = 0.55
        outer_rect = QRectF(chart_x, chart_y, chart_size, chart_size)
        inner_rect = QRectF(
            chart_x + chart_size * (1 - inner_pct) / 2,
            chart_y + chart_size * (1 - inner_pct) / 2,
            chart_size * inner_pct,
            chart_size * inner_pct,
        )

        angles = self._arc_angles()
        if not angles:
            # Zero state — gray circle
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3a3a"))
            p.drawPie(outer_rect, 0, 360 * 16)
            p.setBrush(QColor("#2a2a2a"))
            p.drawEllipse(inner_rect)
        else:
            p.setPen(QPen(QColor("#3c3c3c"), 2))
            for start, span, color in angles:
                p.setBrush(color)
                p.drawPie(outer_rect, int(start), int(span))
            # Inner cutout
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3c3c3c"))
            p.drawEllipse(inner_rect)

        # Center text
        if self._data:
            total = sum(d["count"] for d in self._data)
            p.setPen(QColor("#d9d9d9"))
            font = QFont("Noto Sans", 14, QFont.Weight.Bold)
            p.setFont(font)
            center_rect = QRectF(
                inner_rect.left(), inner_rect.top() + inner_rect.height() * 0.35,
                inner_rect.width(), 20,
            )
            p.drawText(center_rect, Qt.AlignmentFlag.AlignCenter, str(total))
            center_rect.moveTop(center_rect.top() + 18)
            p.setFont(QFont("Noto Sans", 9))
            p.setPen(QColor("#a1a1aa"))
            p.drawText(center_rect, Qt.AlignmentFlag.AlignCenter, "clips")

        # Legend
        legend_x = chart_x + chart_size + 12
        legend_y = chart_y + 4
        fm = QFontMetrics(QFont("Noto Sans", 10))
        p.setFont(QFont("Noto Sans", 10))

        for label, value, color in self._legend:
            # Color swatch
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            swatch = QRect(legend_x, legend_y, 10, 10)
            p.drawRoundedRect(QRectF(swatch), 2, 2)

            # Label
            p.setPen(QColor("#d9d9d9"))
            text_width = 100
            text = fm.elidedText(label, Qt.TextElideMode.ElideRight, text_width)
            p.drawText(QRect(legend_x + 16, legend_y, text_width, 16), Qt.AlignmentFlag.AlignLeft, text)

            # Value
            p.setPen(QColor("#a1a1aa"))
            val_width = 60
            p.drawText(QRect(legend_x + 16 + text_width, legend_y, val_width, 16),
                       Qt.AlignmentFlag.AlignRight, value)
            legend_y += 18

        p.end()


# ---------------------------------------------------------------------------
# Bar Chart
# ---------------------------------------------------------------------------


class _BarChart(QWidget):
    """Custom QPainter bar chart — captures per day for 30 days."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._data: list[dict] = []
        self._hovered_day: str | None = None
        self.setMouseTracking(True)

    def set_data(self, uploads_per_day: list[dict]) -> None:
        """Accept list of ``{date, count}`` dicts."""
        self._data = uploads_per_day
        self.update()

    def mouseMoveEvent(self, event) -> None:
        """Track hover position for tooltip."""
        if not self._data:
            return
        bar_w = (self.width() - 40) / 30
        idx = int((event.pos().x() - 30) / bar_w)
        if 0 <= idx < 30:
            # Use same slot→date mapping as paintEvent
            dates = sorted({d["date"] for d in self._data})
            date_idx = len(dates) - 30 + idx
            if 0 <= date_idx < len(dates):
                self._hovered_day = dates[date_idx]
                self.update()
                return
        self._hovered_day = None
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered_day = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        margin_left, margin_right, margin_bottom, margin_top = 30, 10, 24, 16
        chart_w = w - margin_left - margin_right
        chart_h = h - margin_top - margin_bottom

        if not self._data:
            # Zero state
            p.setPen(QColor("#a1a1aa"))
            p.setFont(QFont("Noto Sans", 11))
            p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No data yet")
            p.end()
            return

        date_map = {d["date"]: d["count"] for d in self._data}
        dates = sorted(date_map.keys())
        max_count = max(date_map.values()) if date_map else 1

        # Axes
        p.setPen(QPen(QColor("#555555"), 1))
        # X axis
        p.drawLine(margin_left, h - margin_bottom, w - margin_right, h - margin_bottom)
        # Y axis
        p.drawLine(margin_left, margin_top, margin_left, h - margin_bottom)

        bar_w = max(4, chart_w / 30 - 2)
        gap = 1

        # Draw bars for each day slot (30 slots)
        for slot in range(30):
            # Find the date for this slot (from end backwards)
            date_idx = len(dates) - 30 + slot
            if date_idx < 0 or date_idx >= len(dates):
                # Empty slot — draw thin line
                x = margin_left + slot * (bar_w + gap)
                p.setPen(QPen(QColor("#3a3a3a"), 1))
                p.drawLine(int(x + bar_w / 2), h - margin_bottom, int(x + bar_w / 2), h - margin_bottom - 2)
                continue

            date = dates[date_idx]
            count = date_map.get(date, 0)
            bar_h_val = (count / max(max_count, 1)) * chart_h

            x = margin_left + slot * (bar_w + gap)
            y = h - margin_bottom - bar_h_val

            is_hovered = self._hovered_day == date
            color = QColor("#60a5fa") if not is_hovered else QColor("#93c5fd")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, y, bar_w, bar_h_val), 2, 2)

        # Hover tooltip
        if self._hovered_day is not None:
            count = date_map.get(self._hovered_day, 0)
            tooltip = f"{self._hovered_day}: {count}"
            p.setPen(QColor("#d9d9d9"))
            p.setFont(QFont("Noto Sans", 10))
            fm = QFontMetrics(p.font())
            tw = fm.horizontalAdvance(tooltip) + 8
            th = 18
            tx = w - tw - 8
            ty = 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#404040"))
            p.drawRoundedRect(QRectF(tx, ty, tw, th), 4, 4)
            p.setPen(QColor("#d9d9d9"))
            p.drawText(QRectF(tx + 4, ty, tw - 4, th), Qt.AlignmentFlag.AlignVCenter, tooltip)

        # Y-axis labels
        p.setPen(QColor("#a1a1aa"))
        p.setFont(QFont("Noto Sans", 8))
        for i in range(3):
            y_val = max_count * (3 - i) / 3
            y_pos = h - margin_bottom - int((y_val / max(max_count, 1)) * chart_h)
            p.drawText(QRect(0, y_pos - 8, margin_left - 4, 16), Qt.AlignmentFlag.AlignRight, str(int(y_val)))

        p.end()


# ---------------------------------------------------------------------------
# Stats Page
# ---------------------------------------------------------------------------


class StatsPage(QWidget):
    """Dashboard page with clip metrics, charts, and recent uploads table."""

    clip_activated = pyqtSignal(str)

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store

        # --- Scroll area for the full dashboard ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(12)

        # --- Title row ---
        title_row = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        content_layout.addLayout(title_row)

        # --- Metric cards ---
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(12)
        self._card_total = _MetricCard("🎬", "Total Clips")
        self._card_storage = _MetricCard("💾", "Storage Used")
        self._card_today = _MetricCard("📤", "Uploads Today")
        self._card_week = _MetricCard("📅", "Uploads This Week")
        metrics_grid.addWidget(self._card_total, 0, 0)
        metrics_grid.addWidget(self._card_storage, 0, 1)
        metrics_grid.addWidget(self._card_today, 1, 0)
        metrics_grid.addWidget(self._card_week, 1, 1)
        content_layout.addLayout(metrics_grid)

        # --- Charts row ---
        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        # Donut chart in a card
        donut_card = QFrame()
        donut_card.setObjectName("chartCard")
        donut_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        donut_layout = QVBoxLayout(donut_card)
        donut_layout.setContentsMargins(12, 8, 12, 8)
        donut_title = QLabel("Top Games")
        donut_title.setObjectName("cardTitle")
        donut_layout.addWidget(donut_title)
        self._donut_chart = _DonutChart()
        donut_layout.addWidget(self._donut_chart, stretch=1)
        charts_row.addWidget(donut_card, stretch=1)

        # Bar chart in a card
        bar_card = QFrame()
        bar_card.setObjectName("chartCard")
        bar_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        bar_layout = QVBoxLayout(bar_card)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        bar_title = QLabel("Captures (30 days)")
        bar_title.setObjectName("cardTitle")
        bar_layout.addWidget(bar_title)
        self._bar_chart = _BarChart()
        bar_layout.addWidget(self._bar_chart, stretch=1)
        charts_row.addWidget(bar_card, stretch=2)

        content_layout.addLayout(charts_row, stretch=1)

        # --- Recent uploads table ---
        table_card = QFrame()
        table_card.setObjectName("chartCard")
        table_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 8, 12, 8)
        table_title = QLabel("Recent Uploads")
        table_title.setObjectName("cardTitle")
        table_layout.addWidget(table_title)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Title", "Game", "Date", "Size"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
                color: var(--text-primary);
                gridline-color: var(--border-menu);
                font-family: "Noto Sans", sans-serif;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid var(--border-window);
            }
            QTableWidget::item:selected {
                background-color: #2a3a45;
            }
            QHeaderView::section {
                background-color: transparent;
                color: var(--text-secondary);
                border: none;
                border-bottom: 1px solid var(--border-menu);
                padding: 6px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        self._table.cellClicked.connect(self._on_table_cell_clicked)
        table_layout.addWidget(self._table)
        content_layout.addWidget(table_card)

        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # Signal is defined at class level below

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Load aggregate stats from the store and update all widgets."""
        if self._store is None:
            self._show_zero_state()
            return

        try:
            stats = self._store.get_aggregate_stats()
        except Exception as exc:
            logger.exception("Failed to load stats")
            self._show_zero_state()
            return

        self._card_total.set_value(str(stats["total_clips"]))
        self._card_storage.set_value(_human_size(stats["total_storage_bytes"]))
        self._card_today.set_value(str(stats["uploads_today"]))
        self._card_week.set_value(str(stats["uploads_this_week"]))

        self._donut_chart.set_data(stats["clips_per_game"])
        self._bar_chart.set_data(stats["uploads_per_day"])

        self._populate_table(stats["recent_uploads"])

    # ==================================================================
    # Internals
    # ==================================================================

    def _show_zero_state(self) -> None:
        """Show zeros / empty state across all widgets."""
        self._card_total.set_value("0")
        self._card_storage.set_value("0 B")
        self._card_today.set_value("0")
        self._card_week.set_value("0")
        self._donut_chart.set_data([])
        self._bar_chart.set_data([])
        self._table.setRowCount(0)

    def _populate_table(self, uploads: list[dict]) -> None:
        """Fill the recent uploads table."""
        self._table.setRowCount(len(uploads))
        for i, u in enumerate(uploads):
            title = u.get("title", "") or "—"
            game = u.get("game") or "—"
            date = _parse_date(u.get("uploaded_at"))
            size = _human_size(u.get("file_size", 0))

            self._table.setItem(i, 0, QTableWidgetItem(title))
            self._table.setItem(i, 1, QTableWidgetItem(game))
            self._table.setItem(i, 2, QTableWidgetItem(date))
            self._table.setItem(i, 3, QTableWidgetItem(size))

            # Store clip ID in the title item for click navigation
            clip_id = u.get("id", "")
            self._table.item(i, 0).setData(Qt.ItemDataRole.UserRole, clip_id)

    def _on_table_cell_clicked(self, row: int, col: int) -> None:
        """Navigate to player when a recent upload row is clicked."""
        item = self._table.item(row, 0)
        if item is None:
            return
        clip_id = item.data(Qt.ItemDataRole.UserRole)
        if clip_id:
            self.clip_activated.emit(clip_id)
