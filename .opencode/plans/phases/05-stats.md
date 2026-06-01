# Phase 5: Stats — stats_page.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Enhance the stats page: 4 metric cards, donut chart widget, bar chart widget, table view.

## Page Layout
- Margins: 16px (density-aware)
- Top row: 4 metric cards, equal width in horizontal layout
- Middle row: 2 columns (donut left 50%, bar right 50%), 12px gap
- Bottom: full-width QTableView (game breakdown)

## Metric Cards (replacing `_MetricCard`)
- QFrame: `background: #242424`, `border: 1px solid #3d3d3d`, `border-radius: 6px`
- Layout: icon left (24×24 outline, accent-colored) + value (22px bold) + label (12px secondary) stacked right
- Icon colors: clips → green `#34d399`, time → blue `#4a9eff`, storage → orange `#fbbf24`, avg → teal `#14b8a6`
- No hover state

## Donut Chart (QWidget + QPainter)
- Size: ~280×280
- Segments: `drawPie` or `drawArc`, 2px gap between segments
- 12 distinct chart colors for game segments
- Center hole: 40% of radius
- Center text: total count (24px bold) + "total clips" (11px muted)
- Hover: segment expands 2px outward, PointingHandCursor, +20% brightness
- Legend below: 8px colored dot + label (11px) + value (11px), 4px gap

## Bar Chart (QWidget + QPainter)
- Height: 220px
- Title: "Clips per Game" (15px bold) above
- Vertical bars, equal width (min 20px), rounded top only (radius 3px)
- Gradient fill: +30% brightness top → base color bottom
- Y-axis: dashed gridlines at 25/50/75/100%, 10px gray labels
- X-axis: labels rotated 30° if >6 bars, 11px --text-secondary
- Hover: QToolTip with game + exact count, bar gets 1px bright border

## Table View (bottom)
- QTableView: cols = Game, Clips, Total Time, Avg Duration, Last Recorded
- Header: bg `#1e1e1e`, color `#a0a0a0`, 12px, bottom border `#3d3d3d`
- Rows: alternating `#242424` / `#1e1e1e`, 11px --text-secondary
- Selection: row highlight `#323232`
- No grid lines (OnlyOffice style)

## Refresh Button
- Floating top-right, 28px height, icon + "Refresh" text
- Secondary line-style

## Acceptance
- 4 metric cards render with correct values and icon colors
- Donut chart draws game segments, hover works
- Bar chart draws bars with gradient, hover shows tooltip
- Table has correct columns and alternating rows
- Refresh button works
