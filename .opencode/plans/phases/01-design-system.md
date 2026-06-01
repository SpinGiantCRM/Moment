# Phase 1: Design System — resources.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Rewrite `src/moment/ui/resources.py` with the new palette, typography, spacing, QSS, and icon loader.

## New Constants

### Colour tokens
Replace `_COLOUR_TOKENS` with the full palette from total truth §3 (45+ tokens).

### Typography system
```python
_TYPOGRAPHY = {
    "caption":     (10, 14, 600, True),    # size, lineHeight, weight, uppercase
    "small":       (11, 16, 400, False),
    "label":       (12, 16, 500, False),
    "body":        (13, 18, 400, False),
    "body-bold":   (13, 18, 600, False),
    "body-large":  (14, 20, 400, False),
    "subtitle":    (15, 20, 600, False),
    "title":       (18, 24, 600, False),
    "heading":     (22, 28, 700, False),
    "display":     (28, 34, 700, False),
}
```
Helper: `set_font(widget, token)` applies family + size + weight.

### Spacing scale
```python
_SPACING = {"space-1": 2, "space-2": 4, ..., "space-10": 48}
_DENSITY = {"compact": 0.85, "normal": 1.0, "comfortable": 1.15}
apply_spacing(spacing_token, density="normal")  -> int
```

### Helper functions
- `load_icon(name, color)` — loads SVG from `assets/icons/`, returns QIcon (uses QSvgRenderer → QPixmap or QIcon(path))
- `set_font(widget, token)` — applies family + size + weight from `_TYPOGRAPHY`
- `apply_spacing(token, density)` — returns px after density multiplier

## QSS Rules
Replace existing `_QSS_WIDGET_RULES` with all rules below. Use `_COLOUR_TOKENS` for all colors (so palette changes propagate everywhere).

Apply QSS for:
- QMainWindow / QWidget base (font-family, bg #1a1a1a, text #e8e8e8)
- QPushButton `#primary` — filled blue (#4a9eff)
- QPushButton `#secondary` — line-style (transparent bg, 1px border #555555)
- QPushButton `#danger` — red line-style (border #f87171)
- QTabWidget / QTabBar — clean OnlyOffice tabs (bottom-border active indicator)
- QComboBox — compact (28px, border #444444, chevron icon)
- QLineEdit / QTextEdit — 28px, border #444444, focus #4a9eff
- QCheckBox / QRadioButton — accent #4a9eff, 16px indicator
- QScrollBar — 6px thin, transparent track, #444444 handle
- QSplitter — 1px #2a2a2a handle
- QMenu — context menus, #242424 bg, #323232 selection
- QToolTip — #2a2a2a bg, 11px
- QSlider — 4px track, #4a9eff fill, white thumb with blue border
- `#sidebarBtn` — QToolButton: centered 24px icon, transparent, hover bg #323232
- `#sidebarBtn:checked` — border-left 2px #4a9eff, icon accent
- `#toolbarAction` — QPushButton: secondary line-style, 28px height
- `#cardSizeToggle` — QToolButton: 20px icon, checked accent-colored
- `#statusBarLabel` — 11px, --text-muted
- `#processingLabel` — 12px, --text-secondary
- `#emptyStateIcon` — QLabel (pixmap)
- `#emptyStateHeading` — 18px bold, --text-primary
- `#emptyStateDesc` — 13px, --text-secondary

## Acceptance
- `make run` shows no import errors from resources.py
- QSS rules are valid and don't crash Qt
- `load_icon("library", "#a0a0a0")` returns a valid QIcon
- `set_font(widget, "title")` applies 18px/24px/600

## Design system references
- Full palette: ui-revamp.md §3
- Typography: ui-revamp.md §1
- Spacing: ui-revamp.md §2
- Elevation/radius: ui-revamp.md §4
- Animation: ui-revamp.md §5
- Icons: ui-revamp.md §6
- QSS rules: ui-revamp.md §1 in Changes by File
