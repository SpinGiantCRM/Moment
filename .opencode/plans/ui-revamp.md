# Plan: UI Revamp — Medal Architecture + OnlyOffice Design (OPEN)

**This is the total truth reference.** Phase files in `phases/` contain scoped extracts. Always read the relevant phase file for execution; come here for systemic/cross-cutting questions.

## Phase Files
| # | File | Scope |
|---|------|-------|
| 0 | `phases/00-icons.md` | All SVG icons (assets/icons/) |
| 1 | `phases/01-design-system.md` | resources.py — palette, typography, spacing, QSS, icon loader |
| 2 | `phases/02-layout.md` | main_window.py — sidebar, toolbar, processing footer, status bar |
| 3 | `phases/03-cards.md` | clip_delegate.py (3 card sizes) + grid_page.py (layout, empty state) |
| 4 | `phases/04-player.md` | player_page.py — video, transport overlay, seek bar, metadata |
| 5 | `phases/05-stats.md` | stats_page.py — metric cards, donut/bar charts, table |
| 6 | `phases/06-settings.md` | settings_dialog.py — two-panel, toggle switch, form controls |
| 7 | `phases/07-rest-pages.md` | trash_page, recording_page, webhook_page, app.py cleanup |

## Design Direction

| Aspect | Decision |
|--------|----------|
| Core architecture | Medal.tv — clip grid, sidebar nav, focus on clips |
| Design aesthetic | ONLYOFFICE — clean, professional, productivity feel |
| Sidebar | Icon-only, 56px, OnlyOffice-style vertical icon strip |
| Top toolbar | Context toolbar: search bar + sort dropdown + page-specific line-style actions + card-size toggles |
| Cards | 3 sizes (small/medium/large) toggled from toolbar |
| Processing footer | Auto-hide bottom bar (slides up when pipeline tasks active, hidden when idle) |
| Status bar | Left: recording indicator + hotkey. Right: storage used/total |
| Empty states | Rich: illustration icon + heading + description + CTA button per page |
| Context menu | Play, Share, Download, Delete front-facing; More submenu for deeper actions |
| Selection mode | Heart toggle visible on card corner (like checkbox) |
| Search history | Session-only: recent searches as chips below search bar, cleared on restart |
| Page transitions | QPropertyAnimation fade, 200ms |
| Density | Normal default; user-adjustable (compact/normal/comfortable) in settings |
| Visual mood | Medium-dark surfaces, clear borders, blue accent (#4a9eff), onlyoffice professional |
| Accent color | **#4a9eff** (OnlyOffice blue) — all interactive elements, focus states, active indicators |
| Font default | Open Sans (OnlyOffice's UI font); user-configurable in settings |
| Thumbnail loading | Skeleton pulse — gray placeholder with shimmer animation |
| Scope | Full revamp — sidebar + toolbar + cards + charts + dialogs + all pages |

## Design System

### 1. Typography

```
--font-family: "Open Sans", "Segoe UI", "Roboto", sans-serif
--font-mono:   "JetBrains Mono", "SF Mono", "Consolas", monospace

--text-caption:     10px/14px  600 uppercase    (badges, category headers)
--text-small:       11px/16px  400               (timecodes, file sizes, version)
--text-label:       12px/16px  500               (form labels, sidebar labels)
--text-body:        13px/18px  400               (default: metadata, settings, table rows)
--text-body-bold:   13px/18px  600               (emphasized body, button text)
--text-body-large:  14px/20px  400               (section headers, metric values)
--text-subtitle:    15px/20px  600               (card titles, page subtitles)
--text-title:       18px/24px  600               (page titles, dialog titles)
--text-heading:     22px/28px  700               (welcome message, large stat numbers)
--text-display:     28px/34px  700               (hero stats — total clips, total time)

--letter-spacing-dark: 0.02em  (global increase for dark-mode readability — OnlyOffice pattern)
```

**Application by widget:**
- Sidebar tooltips: 12px
- Sidebar icons: 24×24
- Page title (e.g. "Library"): 18px bold
- Clip card title: 13px body (truncated to 1 line)
- Clip card metadata: 11px small (date, duration, game)
- Metric card values: 22px bold heading
- Metric card labels: 12px label
- Settings section headers: 15px bold, capitalized
- Settings labels: 13px, right-aligned
- Settings values: 13px
- Status bar: 11px small
- Processing footer: 12px label
- Context menu items: 13px
- Search bar text: 13px
- Dropdown text: 13px
- Button text: 13px bold (primary), 13px (secondary)
- Toggle switch labels: 13px
- Empty state heading: 18px bold
- Empty state description: 13px

### 2. Spacing System (4px grid)

```
--space-1:  2px   (micro spacing, edge padding for tiny elements)
--space-2:  4px   (tight spacing, icon-to-label gaps)
--space-3:  8px   (element gaps, button groups)
--space-4:  12px  (card padding, toolbar padding)
--space-5:  16px  (page margins, section spacing)
--space-6:  20px  (large gaps between sections)
--space-7:  24px  (dialog spacing, very large gaps)
--space-8:  32px  (page heading from content)
--space-9:  40px  (section hero spacing)
--space-10: 48px  (maximum breathing room)
```

**Density scaling (multiplier on base spacing):**
- Compact: 0.85× (tighter grid, smaller card gaps)
- Normal: 1.0× (default)
- Comfortable: 1.15× (more breathing room, premium feel)

**Application by context:**
- Window padding: 0 (pages provide their own)
- Toolbar horizontal padding: 12px left/right
- Sidebar internal padding: 8px top, 8px bottom, 0 sides
- Sidebar icon-to-edge: centered (56px width centers 24px icon = 16px each side)
- Card grid margins: 16px (normal density)
- Card gaps: 12px (normal density)
- Card padding: 12px content, 8px metadata row
- Form row spacing: 8px between rows, 20px between sections
- Dialog padding: 24px content area, 16px left panel
- Button padding: 6px 16px (primary), 5px 15px (secondary — 1px border compensation)
- List item padding: 8px 12px
- Context menu: 4px internal padding per item, 6px horizontal

### 3. Color Palette

```
--bg-window:          #1a1a1a    (main window background)
--bg-surface:         #242424    (card/section surface)
--bg-elevated:        #2a2a2a    (hovered cards, floating elements, menus)
--bg-inset:           #1e1e1e    (input fields, text edits, toolbar)
--bg-hover:           #323232    (button hover, list item hover, nav hover)
--bg-active:          #3a3a3a    (active/selected item, pressed state)
--bg-sidebar:         #181818    (main left nav, settings dialog left panel)
--bg-toolbar:         #1e1e1e    (top toolbar background)
--bg-overlay:         rgba(0,0,0,0.65)  (video controls overlay)
--bg-skeleton:        #2a2a2a    (thumbnail loading placeholder base)
--bg-skeleton-shimmer: #333333   (skeleton shimmer highlight)

--border-default:     #2a2a2a    (window edge, panel separators)
--border-subtle:      #3d3d3d    (card borders, divider lines, inactive tab borders)
--border-input:       #444444    (input fields, dropdown borders)
--border-focus:       #4a9eff    (focused input, active tab indicator, selected card)
--border-hover:       #555555    (button hover border, card hover border)

--text-primary:       #e8e8e8    (headings, body text, high-emphasis)
--text-secondary:     #a0a0a0    (labels, metadata, help text, medium-emphasis)
--text-muted:         #6b6b6b    (disabled text, placeholders, low-emphasis)
--text-link:          #4a9eff    (clickable links, interactive text)
--text-on-accent:     #ffffff    (text on filled accent backgrounds)

--btn-primary-bg:     #4a9eff
--btn-primary-hover:  #3a8ae8
--btn-primary-pressed:#2a7ad8
--btn-primary-text:   #ffffff
--btn-secondary-bg:   transparent
--btn-secondary-border: #555555
--btn-secondary-hover-bg: #323232
--btn-secondary-hover-border: #666666
--btn-secondary-text: #e8e8e8
--btn-danger-border:  #f87171
--btn-danger-text:    #f87171
--btn-danger-hover-bg: rgba(248,113,113,0.1)
--btn-disabled-bg:    #2a2a2a
--btn-disabled-text:  #555555

--toggle-active:      #4a9eff    (ON track color)
--toggle-inactive:    #444444    (OFF track color)
--toggle-knob:        #ffffff    (knob fill)
--toggle-knob-shadow: rgba(0,0,0,0.3) (knob drop shadow)
--toggle-hover:       #555555    (OFF track hover)

--slider-track:       #444444    (volume/seek track background)
--slider-fill:        #4a9eff    (volume/seek progress fill)
--slider-thumb:       #ffffff    (slider knob)

--accent-blue:        #4a9eff
--accent-green:       #34d399
--accent-orange:      #fbbf24
--accent-red:         #f87171
--accent-gold:        #f59e0b    (favorite star)

--heart-inactive:     #555555    (favorite heart unfilled)
--heart-active:       #f87171    (favorite heart filled — red, not gold)
```

### 4. Elevation & Borders

```
--radius-sm:      2px    (micro elements, sliders)
--radius-md:      3px    (buttons, inputs, dropdowns, tabs)
--radius-lg:      6px    (cards, dialogs, panels)
--radius-full:    9999px (pills, badges, toggles)

--elevation-flat:   none (default: cards use 1px border)
--elevation-raised: 1px border (on hover/selected, border brightens to #555555)
--elevation-dialog: 1px border + subtle overlay behind dialog
--elevation-popup:  1px border + background change (menu, tooltip)
```

Do NOT use drop shadows anywhere. Use border color changes and background shifts instead (OnlyOffice philosophy — clean, flat, no shadows).

### 5. Animation System

```
--ease-out:     cubic-bezier(0.0, 0.0, 0.2, 1.0)    (deceleration, for entering elements)
--ease-in-out:  cubic-bezier(0.4, 0.0, 0.2, 1.0)    (standard, for toggles/transitions)

--duration-instant: 0ms     (immediate state change)
--duration-fast:    50ms    (micro-interactions, hover start)
--duration-normal:  100ms   (hover end, active/pressed)
--duration-slow:    150ms   (toggle switch, checkbox transitions)
--duration-page:    200ms   (page crossfade, panel slide)
--duration-emphasis: 300ms  (special state transitions)
```

**Animation by widget:**
- Hover (enter): 50ms, property: background-color
- Hover (exit): 100ms, property: background-color
- Active/pressed: 50ms instant
- Toggle switch: 150ms ease-in-out, property: knob position geometry
- Page transition: 200ms ease-in-out, property: QWidget opacity (QPropertyAnimation)
- Panel auto-show (processing footer): 200ms ease-out, property: max-height/opacity
- Skeleton shimmer: 1.5s infinite loop, keyframe-like color shift
- Checkbox state: 100ms ease-in-out

Use `QPropertyAnimation` for custom widgets (toggle switch, page fade).
Use QSS `:hover` pseudo-state (instant) for button/list hover; the transition speed is handled by `QToolButton { transition: background-color 50ms ease-out; }` in QSS (if Qt supports it — not all QSS properties animate, test per-platform; fallback: no animation).

### 6. Icon System

**Style:** Outline, stroke-width 1.5, currentColor (fill="none" for most), 24×24 viewBox.
**Color:** Default `#a0a0a0` (text-secondary), active/hover `#4a9eff` (accent-blue), white on dark overlays.

#### Sidebar icons (7 total, in `assets/icons/`):
| Icon | Path description |
|------|-----------------|
| `library.svg` | 3×3 grid of squares — two rows visible, top row filled |
| `record.svg` | Solid circle (filled, no outline — record dot), 20px diameter centered |
| `player.svg` | Play triangle pointing right, slightly rounded corners |
| `stats.svg` | Bar chart — 3 bars ascending: short, medium, tall, rounded tops |
| `trash.svg` | Trash bin outline: wider top, narrower bottom, lid line |
| `webhooks.svg` | Link chain link — 2 interlocking chain segments |
| `settings.svg` | Gear with 6 teeth, centered hole |

#### Toolbar icons:
- `search.svg` — Magnifying glass, 45° angle handle
- `sort.svg` — Two arrows: up & down, vertical alignment
- `view-grid-small.svg` — 3×3 dense grid
- `view-grid-medium.svg` — 2×2 grid (current/default)
- `view-grid-large.svg` — 1-column list style
- `refresh.svg` — Circular arrow, clockwise

#### Player transport icons:
- `play.svg` — Right-pointing triangle
- `pause.svg` — Two vertical bars
- `skip-back.svg` — Triangle pointing left + vertical bar to left
- `skip-forward.svg` — Triangle pointing right + vertical bar to right
- `volume.svg` — Speaker cone with sound waves (3 arcs descending)
- `volume-muted.svg` — Speaker cone with X through it
- `fullscreen.svg` — Diagonal arrows pointing outward (expand)
- `fullscreen-exit.svg` — Diagonal arrows pointing inward (collapse)

#### Action icons:
- `share.svg` — Three connected nodes (network/share symbol)
- `download.svg` — Down arrow into a tray
- `edit.svg` — Pencil at 45°
- `delete.svg` — Trash bin (same as sidebar but simpler)
- `restore.svg` — Curved arrow pointing backward
- `heart.svg` — Heart outline (stroke, for unfavorited)
- `heart-filled.svg` — Heart filled (for favorited)
- `check.svg` — Checkmark
- `close.svg` — X
- `add.svg` — Plus sign
- `more.svg` — Three horizontal dots (more/overflow menu)

#### Status icons:
- `processing.svg` — Spinning circle (or rotate animation placeholder)
- `error.svg` — Exclamation in circle
- `warning.svg` — Triangle with exclamation
- `info.svg` — Letter "i" in circle
- `empty-library.svg` — Icon for empty state (per page)

**Storage:** All SVGs in `src/moment/ui/assets/icons/`. Loaded via a helper function that reads the SVG and creates a `QSvgRenderer` or sets as `QIcon`.

### 7. Layout Architecture

```
┌──────┬──────────────────────────────────────────┐
│      │  Context Toolbar (36px)                   │
│      │  [Search...] [Sort ▼] | [Actions] | [≡]  │
│ Nav  ├──────────────────────────────────────────┤
│ Bar  │  Page Content (QStackedWidget)            │
│ 56px │  - Library (GridPage)                     │
│ icon │  - Player (PlayerPage)                    │
│ only │  - Record (RecordingPage)                 │
│      │  - Stats (StatsPage)                      │
│      │  - Trash (TrashPage)                      │
│      │  - Webhooks (WebhookPage)                 │
│      │                                           │
├──────┴──────────────────────────────────────────┤
│  Processing Footer (auto-hide, 32px)             │
│  Recording ● Encoding ■ Uploading ▲ [progress]   │
├─────────────────────────────────────────────────┤
│  Status Bar (24px)                               │
│  ● Recording ready    Ctrl+F12          45/256GB │
└─────────────────────────────────────────────────┘
```

**Sizing:**
- Sidebar width: 56px (fixed)
- Toolbar height: 36px
- Page content: fills remaining space
- Processing footer: 32px (auto-hides to 0)
- Status bar: 24px (always visible)

## Changes by File

### 1. `resources.py` — Full Design System Refresh

**New constants:**
- `_COLOUR_TOKENS` → replace with the full palette above (from §3)
- `_TYPOGRAPHY` dict with all font sizes/weights from §1
- `_SPACING` dict with spacing scale from §2
- `_RADIUS` dict with border-radius values from §4
- `_ANIMATION` dict with durations from §5
- `_DENSITY` dict with scale multipliers (0.85/1.0/1.15)
- `ICON_DIR` path to `assets/icons/`
- `load_icon(name, color)` — loads SVG, returns QIcon (uses QSvgRenderer patched into QPixmap, or simply QIcon(path))
- `set_font(widget, token)` — applies font family + size + weight from the typography system

**QSS rules to rewrite:**

**QMainWindow / QWidget (base):**
```css
QMainWindow, QWidget {
    background-color: #1a1a1a;
    color: #e8e8e8;
    font-family: "Open Sans", "Segoe UI", "Roboto", sans-serif;
    font-size: 13px;
}
```

**QPushButton — Primary (filled, accent):**
```css
QPushButton#primary, QPushButton[class="primary"] {
    background: #4a9eff;
    color: #ffffff;
    border: 1px solid #4a9eff;
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#primary:hover {
    background: #3a8ae8;
    border-color: #3a8ae8;
}
QPushButton#primary:pressed {
    background: #2a7ad8;
}
```

**QPushButton — Secondary (line-style):**
```css
QPushButton#secondary, QPushButton[class="secondary"] {
    background: transparent;
    border: 1px solid #555555;
    color: #e8e8e8;
    border-radius: 3px;
    padding: 5px 15px;
    font-size: 13px;
}
QPushButton#secondary:hover {
    background: #323232;
    border-color: #666666;
}
```

**QPushButton — Danger:**
```css
QPushButton#danger {
    border: 1px solid #f87171;
    color: #f87171;
    background: transparent;
    border-radius: 3px;
    padding: 5px 15px;
    font-size: 13px;
}
QPushButton#danger:hover {
    background: rgba(248, 113, 113, 0.1);
}
```

**QTabWidget / QTabBar (OnlyOffice clean tabs):**
```css
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: #a0a0a0;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 16px;
    font-size: 13px;
    min-height: 28px;
}
QTabBar::tab:selected {
    color: #e8e8e8;
    border-bottom: 2px solid #4a9eff;
}
QTabBar::tab:hover:!selected {
    color: #e8e8e8;
    background: #242424;
}
QTabBar::tab:!selected {
    margin-top: 2px;
}
```

**QComboBox (OnlyOffice compact):**
```css
QComboBox {
    background: #1e1e1e;
    border: 1px solid #444444;
    border-radius: 3px;
    color: #e8e8e8;
    font-size: 13px;
    padding: 0 8px;
    min-height: 28px;
    max-height: 28px;
}
QComboBox:hover {
    border-color: #555555;
}
QComboBox:focus, QComboBox:on {
    border-color: #4a9eff;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
    background: transparent;
}
QComboBox::down-arrow {
    image: url(assets/icons/chevron-down.svg);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: #242424;
    border: 1px solid #3d3d3d;
    border-radius: 3px;
    selection-background-color: #323232;
    selection-color: #e8e8e8;
    color: #e8e8e8;
    padding: 4px;
    outline: none;
}
```

**QLineEdit / QTextEdit:**
```css
QLineEdit, QTextEdit {
    background: #1e1e1e;
    border: 1px solid #444444;
    border-radius: 3px;
    color: #e8e8e8;
    font-size: 13px;
    padding: 0 8px;
    min-height: 28px;
    selection-background-color: #4a9eff;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #4a9eff;
}
QLineEdit:disabled, QTextEdit:disabled {
    background: #242424;
    color: #555555;
    border-color: #3d3d3d;
}
```

**QCheckBox / QRadioButton:**
```css
QCheckBox, QRadioButton {
    color: #e8e8e8;
    font-size: 13px;
    spacing: 6px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background: #1e1e1e;
}
QCheckBox::indicator:checked {
    background: #4a9eff;
    border-color: #4a9eff;
}
QRadioButton::indicator {
    border-radius: 8px;
}
QRadioButton::indicator:checked {
    background: #4a9eff;
    border-color: #4a9eff;
}
```

**QScrollBar:**
```css
QScrollBar:vertical {
    width: 6px;
    background: transparent;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #444444;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #555555;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    background: none;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
/* Horizontal same but with height: 6px */
```

**QSplitter:**
```css
QSplitter::handle {
    background: #2a2a2a;
    width: 1px;
}
```

**QMenu (context menus):**
```css
QMenu {
    background: #242424;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 12px;
    border-radius: 3px;
    color: #e8e8e8;
    font-size: 13px;
}
QMenu::item:selected {
    background: #323232;
}
QMenu::separator {
    height: 1px;
    background: #3d3d3d;
    margin: 4px 8px;
}
QMenu::icon {
    padding-left: 4px;
    width: 20px;
    height: 20px;
}
```

**QToolTip:**
```css
QToolTip {
    background: #2a2a2a;
    border: 1px solid #3d3d3d;
    border-radius: 3px;
    color: #e8e8e8;
    font-size: 11px;
    padding: 4px 8px;
}
```

**QSlider (used for volume/seek):**
```css
QSlider::groove:horizontal {
    background: #444444;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid #4a9eff;
}
QSlider::handle:horizontal:hover {
    background: #4a9eff;
}
QSlider::sub-page:horizontal {
    background: #4a9eff;
    border-radius: 2px;
}
```

**New objectName styles:**
- `#sidebarBtn` — QToolButton in sidebar: centered 24×24 icon, no text, no border, transparent bg, hover bg #323232
- `#sidebarBtn:checked` — active nav: border-left: 2px solid #4a9eff, icon color #4a9eff
- `#toolbarAction` — QPushButton in toolbar: secondary line-style, smaller, 28px height
- `#toolbarAction:hover` — hover: border-color #555555, bg #323232
- `#cardSizeToggle` — QToolButton for card-size toggle: 20×20 icon, checked state accent-colored
- `#statusBarLabel` — QLabel in status bar: 11px, --text-muted
- `#processingLabel` — QLabel in processing footer: 12px, --text-secondary
- `#emptyStateIcon` — QLabel (pixmap) for empty state illustrations
- `#emptyStateHeading` — 18px bold, --text-primary
- `#emptyStateDesc` — 13px, --text-secondary, line-height 1.4

### 2. `main_window.py` — Full Layout Rewrite

**Sidebar (icon-only, 56px):**
- Change `SIDEBAR_W` from 76 to 56
- Replace current QPushButton nav with QToolButton for each item
- 7 nav items in order: Library, Record, Player, Stats, Trash, Webhooks (group), then a stretch spacer, then Settings
- Group divider: thin QFrame line `#2a2a2a` before Settings
- Each QToolButton: `setCheckable(True)`, `setAutoExclusive(True)` so only one is checked
- `setObjectName("sidebarBtn")` — QSS handles the visual styling
- `setIcon(load_icon("library", "#a0a0a0"))` — icon loaded from SVG
- On checked state change: change icon color to `#4a9eff` for active, `#a0a0a0` for inactive
- Tooltips: "Library (Ctrl+1)", "Record (Ctrl+2)", etc.

**Sidebar interaction behavior:**
- Click on nav item → `nav_clicked.emit(page_index)` → `self._stack.setCurrentIndex(page_index)`
- Settings button (at bottom) → opens settings dialog, does NOT navigate to a settings page
- When settings dialog opens, the settings icon becomes checked/active (temporarily)

**Context Toolbar (simplified, 36px):**
- Background `#1e1e1e`, 1px bottom border `#2a2a2a`
- Layout (left to right):
  1. Search bar: QLineEdit, objectName `toolbarSearch`, 200px wide, placeholder "Search clips...", clear button (built-in QLineEdit clear)
  2. Recent searches: horizontal flow of QPushButton chips (styled: pill, 11px, `background: #323232`) — shown only when search bar has focus and there are recent searches. Each chip: label text + X to dismiss. Session-only (reset on app restart).
  3. Sort dropdown: QComboBox, 130px wide, options: "Newest", "Name A-Z", "Name Z-A", "Longest", "Shortest"
  4. Separator: vertical QFrame line `#3d3d3d`, 20px height, centered
  5. Page-specific actions: variable set of QPushButton (objectName `toolbarAction`) — filled dynamically per page via `populate_toolbar(actions: list[ToolbarAction])`
  6. Stretch spacer
  7. Card-size toggle group: 3 QToolButtons (small/medium/large) as QButtonGroup exclusive. Checked = current size. `setObjectName("cardSizeToggle")`.
- When no search results: the search bar placeholder changes to "No results found" briefly, or the grid page shows the empty state

**Page stack:**
- QStackedWidget for page content
- On page switch: QPropertyAnimation fade on old widget opacity 1→0 + new widget opacity 0→1, 200ms
- Signal emitted when switch completes: `page_changed(page_index)`
- The processing footer and status bar are OUTSIDE the page stack (persistent)

**Processing Footer (auto-hide, 32px):**
- QFrame at bottom of central widget, above status bar
- Hidden by default (setVisible(False) or height 0)
- When any pipeline task starts: animate height 0→32 with 200ms ease-out
- Layout: icon (processing/upload/encode) + label + progress bar (compact, 4px tall, 100px wide)
- Multiple active tasks: show the most recent, with count badge "2 more"
- Footer auto-hides again when all tasks complete (after 2s delay)
- Styling: `background: #242424`, top border `#3d3d3d`, 12px horizontal padding

**Status Bar (24px, always visible):**
- QFrame at bottom of window
- Left QLabel: recording status (● Recording ready — green dot), small circle icon
- Center QLabel: hotkey hint ("Ctrl+F12 to record a clip"), `--text-muted`
- Right QLabel: storage indicator ("45.2 / 256.0 GB used"), `--text-muted`
- Styling: `background: #181818` (sidebar-dark), top border `#2a2a2a`
- All labels: 11px
- The green recording dot can be an 8×8 circle painted via paintEvent or a tiny QLabel with background #34d399

### 3. `clip_delegate.py` — Card Redesign with 3 Sizes

**Class variable `_card_size`:** `int` enum (0=small, 1=medium, 2=large). Set via `set_card_size(size)` class method called from grid_page when toolbar toggle changes.

**Card dimensions:**
| Size | Card | Thumbnail | Metadata row | Cards per row |
|------|------|-----------|-------------|---------------|
| Small | 200×136 | 184×104 | 32px | floor((width-32)/212) |
| Medium | 272×176 | 256×144 | 32px | floor((width-32)/284) |
| Large | 360×224 | 344×176 | 48px | floor((width-32)/372) |

**Card painting (all sizes):**
1. Background: fill rounded rect `#242424`, border-radius 6px
2. Border: 1px `#3d3d3d`, rect outline with rounded corners
3. Thumbnail: rect at top with 4px top-left/right radius (directly drawn or via clip), bottom 2px radius
4. If thumbnail is None/loading: skeleton pulse — `#2a2a2a` with an animated lighter band (QTimer-based shimmer)

**Skeleton animation:**
- QTimer 16ms (60fps), running for 1.5s per cycle
- Algorithm: gradient-like band at position x that moves left→right
- Band: lighter color `#333333` over base `#2a2a2a`, width 60px
- When image loads: crossfade skeleton to thumbnail (150ms opacity)

**Hover state:**
- Border changes from `#3d3d3d` to `#555555`
- Background stays same (no fill change)
- Heart icon appears (if favorited: filled heart #f87171, if not: outline heart #555555)
- Duration badge stays visible

**Selected state (multi-select, if implemented):**
- Border: 2px `#4a9eff`
- Checkbox visible in top-left corner

**Elements on card (painting order):**

```
┌──────────────────────┐
│ [checkbox]  [heart]  │  ← checkbox (when selectable) + heart (on hover)
│                       │
│    THUMBNAIL          │  ← occupies upper portion
│                       │
│          [3:42]       │  ← duration badge bottom-right of thumb
│                       │
│                       │
├──────────────────────┤
│ Clip Title Here       │  ← 13px bold, truncate 1 line
│ Apr 12 · Valorant     │  ← 11px secondary, dot-separated metadata
└──────────────────────┘
```

**Duration badge:**
- Position: bottom-right of thumbnail, 4px margin from edge
- Background: `rgba(0,0,0,0.8)`, 4px left/right padding, 2px top/bottom
- Border-radius: 3px
- Text: 11px white, monospace font, "M:SS" or "H:MM:SS"

**Heart (Favorite):**
- Position: top-right of card, 6px from edges
- Size: 18×18
- Shown: on hover, or always if favorited
- Default: `#555555` outline heart
- Favorited: `#f87171` filled heart

**Status indicator (optional):**
- Small dot, bottom-left of thumbnail edge
- Colors: green (ready), blue (uploading), orange (encoding), red (error)

**Metadata row:**
- Height: 32px (small/medium), 48px (large — adds second line)
- Horizontal padding: 8px left/right
- Title: 13px bold, 1 line, elided with "..."
- Date + game: 11px secondary, dot-separated
- Large card adds file size + resolution on second line

### 4. `grid_page.py` — Layout Adjustments

- Remove the hidden toolbar island widget entirely
- Remove duplicate search QLineEdit and sort QComboBox (now in main toolbar)
- The grid page receives the page index; on activation, it calls `main_window.populate_toolbar(page_actions)` with its action set
- Grid page actions: empty set (all controls are in the main toolbar: search + sort + size toggle)
- Margins: 16px around (adjusted by density)
- `CARDS_PER_ROW` dynamic: `max(1, (available_width - spacing) // (card_width + spacing))`
- Connect signals from toolbar:
  - `search_text_changed(text)` → `self._proxy.setFilterFixedString(text)` (or your search implementation)
  - `sort_changed(index)` → update QSortFilterProxyModel sort role
  - `card_size_changed(size)` → `ClipDelegate.set_card_size(size)`, invalidate delegate, re-layout
- Recent searches: store in a list, update chips when search activated

**Empty state (shown when proxy model has 0 rows after filtering):**
- Centered in grid area
- Large icon (64×64, `--text-muted`): `empty-library.svg`
- Heading: 18px "No clips yet" or "No results found"
- Description: 13px "Start recording to build your clip library" or "Try different search terms"
- CTA button: primary button "Record a clip" (if no clips at all) or clear search (if filtering)
- Hide empty state whenever model has >0 rows

### 5. `stats_page.py` — Chart Enhancement + Card Redesign

**Page layout:**
- Margins: 16px all around (density-adjusted)
- Top row: 4 metric cards in a horizontal row, equal spacing
- Middle row: 2 columns (donut left, bar right), 12px gap
- Bottom: full-width table/list (recent clips or game breakdown)

**Metric cards:**
- QFrame, 1px border `#3d3d3d`, border-radius 6px, background `#242424`
- Size: flex, equal width in row (~200px)
- Content: icon (24×24, accent-colored outline, left) + value (22px bold) + label (12px secondary) stacked right
- Icon colors: total clips → green `#34d399`, total time → blue `#4a9eff`, storage → orange `#fbbf24`, avg duration → accent (use teal `#14b8a6` for distinction)
- No hover state on metric cards

**Donut chart (QWidget with QPainter):**
- Size: ~280×280
- Background: transparent (inherits page bg)
- Segments: `drawPie` or `drawArc` with 2px gap between segments
- Segment colors: use `_CHART_COLORS` palette (12 distinct colors for games)
- Center hole radius: 40% of chart radius
- Center text: total count (24px bold `--text-primary`) + "total clips" (11px `--text-muted`)
- Hover: segment expands by 2px outward, cursor changes to PointingHandCursor, brightness +20%
- Legend below: colored 8×8 dot + label (11px `--text-secondary`) + value (11px), 4px gap, flow layout

**Bar chart (QWidget with QPainter):**
- Height: 220px
- Title label above: "Clips per Game" (15px bold)
- Bars: vertical, equal width, rounded top using `drawRoundedRect` with radius 3px top only
- Bar width: computed from count of bars, min 20px
- Gradient fill: linear gradient from top (lighter version of color, +30% brightness) to bottom (base color)
- Y-axis: dashed gridlines at 25/50/75/100% of max value, 10px gray labels
- X-axis: labels rotated 30° if >6 bars, 11px `--text-secondary`
- Hover: QToolTip shows exact count + game name; bar gains 1px bright border

**Table view (bottom):**
- QTableView with custom QSS
- Columns: Game, Clips, Total Time, Avg Duration, Last Recorded
- Header style: `background: #1e1e1e`, `color: #a0a0a0`, 12px, `border-bottom: 1px solid #3d3d3d`
- Row style: alternating `#242424` / `#1e1e1e`, 11px `--text-secondary`
- Selection: row highlight `#323232`
- No grid lines (OnlyOffice style)

**Refresh button:**
- Position: floating top-right of page area
- Size: 28px height, icon + text "Refresh"
- Style: secondary line-style

### 6. `settings_dialog.py` — OnlyOffice Settings Dialog

**Dialog structure:**
- Window: QDialog, modal, no help button
- Size: 720×520px default (resizable, min 600×400)
- Left panel: 180px, `background: #181818`
- Right panel: fills remaining, `background: #1a1a1a`
- Separator: 1px `#2a2a2a` vertical line between panels
- Bottom button bar: 1px top border `#2a2a2a`, 48px height, right-aligned buttons

**Category navigation (left panel):**
- QListWidget styled with QSS
- Categories: General, Recording, Video, Hotkeys, Output, Cloud & Storage, About
- Each item: icon (20×20, outline) + label (13px), 8px gap, 12px padding top/bottom, 16px left
- Selected: `background: #323232`, `color: #e8e8e8`, icon accent-blue
- Hover: `background: #2a2a2a`
- Group headers (optional) like "PREFERENCES" in 10px uppercase muted above sections
- Smooth scroll on the list

**Right panel (QStackedWidget for each category):**
- Margins: 24px all around
- Section title: 15px bold, `--text-primary`
- Section divider: 1px `#3d3d3d` line, 16px margin below
- Form rows: label (120px, right-aligned, 13px `--text-secondary`) + control (fills remaining)
- Row height: 32px, centered vertically
- Section spacing: 28px between sections

**Category specifics:**

1. **General** — Theme (dropdown: Dark/Light/System), Interface density (Normal/Compact/Comfortable), Font (current font, dropdown to select), Launch on startup (toggle + dropdown minimized to tray), Minimize to tray on close (toggle), Language (dropdown)
2. **Recording** — Output directory (text input + browse button), Recording mode (dropdown: Game/Desktop/Window), Capture audio (toggle), Microphone (dropdown: devices), Recording FPS (dropdown: 30/60/120/144), Recording resolution (dropdown)
3. **Video** — Encoder (dropdown: NVENC H.264/NVENC H.265/Software), Quality (slider: low/medium/high/lossless), Output format (dropdown: MP4/MKV/MOV), Thumbnail quality (dropdown), Enable GPU acceleration (toggle)
4. **Hotkeys** — Table: command (label) + key sequence input, each row: label (right) + QKeySequenceEdit (left). Save recording, Save recording with replay, Toggle recording, Open overlay
5. **Output** — Auto-upload target (dropdown: None/Google Drive/rclone remote), Clip naming pattern (text input: `{game}_{date}_{time}`), Auto-open after recording (toggle), Keep last N clips (spinbox: unlimited or 50/100/200/500), Storage limit (spinbox + GB unit)
6. **Cloud & Storage** — Connected accounts list, Add account button, Storage used bar (progress bar style, 8px height), Sync settings (toggles for auto-upload, sync on WiFi only)
7. **About** — App version, License type, Check for updates button, Credits/links

**Toggle switch (custom QWidget):**
- Size 44×22, border-radius 11px
- OFF: `background: #444444`, knob left (2px margin from left edge)
- ON: `background: #4a9eff`, knob right (2px margin from right edge)
- Knob: circle 18px diameter, `#ffffff`, subtle inner shadow
- Animation: QPropertyAnimation on knob x position, 150ms
- Click toggles state; emit `toggled(bool)`

**Buttons at bottom:**
- Right-aligned, 8px gap
- Cancel: secondary line-style
- Apply: primary filled
- OK: primary filled, same as Apply but also closes dialog
- All: `border-radius: 3px`, `padding: 6px 20px`, 13px

**Responsive:**
- Dialog remembers its last size/position (QSettings)
- Left panel has a min width, right panel flex

### 7. `player_page.py` — Player UI (Medal-inspired)

**Layout:**
- Top: video area (fills available width/height, min 480p height)
- Below: metadata row + action buttons

**Video display:**
- QWidget with QPainter for video frames (or a QLabel with pixmaps)
- Background: `#0a0a0a` (pure dark for video contrast)
- Video fills container maintaining aspect ratio (`Qt.KeepAspectRatio`)

**Transport controls overlay (bottom of video area):**
- Semi-transparent bar: full width, 48px height, `background: rgba(0,0,0,0.7)`
- Visible on mouse hover over video area + for 3s after last interaction; always visible while paused
- Fade in/out: QPropertyAnimation opacity, 200ms
- Controls centered:
  - Skip back 10s (24×24 icon)
  - Play/Pause (28×28 larger icon, icon switches)
  - Skip forward 10s (24×24 icon)
  - Volume icon (24×24 speaker, click toggles mute)
  - Volume slider (80px horizontal, QSlider styled, 4px track, 12px thumb on hover)
- Fullscreen toggle: right-aligned in bar (24×24 icon)
- All buttons: transparent bg, white icons (painted as white SVGs), hover: slight brighten or scale 1.1

**Seek bar (above transport controls):**
- Full width, 24px hit area (touch-friendly)
- Track visible as 4px line, `background: rgba(255,255,255,0.2)`
- Progress fill: `#4a9eff`
- Thumb: hidden by default, 14px circle on hover (`fill: white`, `stroke: #4a9eff`)
- Hover: track expands to 6px
- Click/drag to seek: jump to position, thumb follows
- Time labels: at ends of seek bar. Left: current time (12px monospace white). Right: total duration (12px monospace `#a0a0a0`)

**Metadata below video:**
- Contain in a horizontal layout, 16px top margin, 16px horizontal margins
- Column 1 (fills most):
  - Title: 18px bold `--text-primary`
  - Row 2: pill badge (game, `background: #323232`, 11px) · date · duration · file size, 13px `--text-secondary`
- Column 2 (right-aligned action buttons):
  - Share / Download: primary filled
  - Edit: secondary line-style
  - Delete: danger line-style

**Empty state (no video loaded):**
- "Select a clip to preview" centered, with icon

### 8. `trash_page.py` — Consistent Layout

- Same grid card rendering as GridPage (uses same ClipDelegate)
- Same card-size toggle (inherited from main toolbar)
- Same grid margins and spacing
- No search bar (search only applies to Library)
- No sort (sorted by deletion date descending always)
- Empty state: "Trash is empty" icon + message + CTA "Go to Library"

**Action differences from Library:**
- Toolbar actions: "Empty Trash" (danger button, right side)
- Context menu on clips: Restore, Delete Permanently, Properties
- Single left-click: opens player
- Cards show deletion date instead of recording date in metadata

### 9. `recording_page.py` — Refine Recording UI

**Layout:**
- Centered content in page area, max 480px wide
- Record button: large pill (120×48px), `border-radius: 24px`
  - Idle: `background: #4a9eff`, "Start Recording"
  - Recording: `background: #f87171` (red), pulsing animation (opacity oscillates between 0.7 and 1.0 every 1s)
- Status indicator below button:
  - Idle: "Ready to record" (13px secondary)
  - Recording: "Recording..." with elapsed time (13px, red dot icon)
  - Error: error message (13px, orange)
- Recording mode selector: 3 pill-style QPushButtons in exclusive group (Game / Desktop / Window), `border-radius: 14px`, 28px height, secondary line style, selected = filled accent
- Hotkey reminder: "Press Ctrl+F12 to start/stop" (11px muted) below mode selector
- Last recordings: horizontal scroll of mini cards (120×80) showing thumbnails of recent 5 clips

**Empty state (no recordings yet):**
- Large record icon
- "No recordings yet"
- "Press Ctrl+F12 or click the button above"
- CTA: "Check your Library" (secondary button)

### 10. `webhook_page.py` — Form Refinements

**Layout:**
- Page title: "Webhooks" (18px bold), margin 16px top
- Subtitle: "Send clip events to external services" (13px secondary)
- Table of webhooks (QTableView):
  - Columns: Name, URL, Events, Last Triggered, Status (enabled/disabled toggle)
  - Same styling as stats page table
  - Status column: small toggle switch (or colored dot)
- Add Webhook button: primary filled, top-right
- Each row: edit (pencil icon) and delete (trash icon) buttons at right

**Empty state:**
- "No webhooks configured"
- "Add a webhook to receive clip events"
- CTA: "Add Webhook" (primary button)

## Implementation Order

| Phase | Files | Description |
|-------|-------|-------------|
| 0. Icons | All SVGs in assets/icons/ | Create all SVG icons needed |
| 1. Design system | `resources.py` | Full palette, typography, spacing, QSS refresh |
| 2. Layout | `main_window.py` | Sidebar icon-only, toolbar, processing footer, status bar |
| 3. Cards | `clip_delegate.py`, `grid_page.py` | 3 card sizes, skeleton, empty state |
| 4. Player | `player_page.py` | Video overlay, transport, seek |
| 5. Stats | `stats_page.py` | Charts + metric cards + table |
| 6. Settings | `settings_dialog.py` | Two-panel, toggles, form |
| 7. Rest | `trash_page.py`, `recording_page.py`, `webhook_page.py` | Consistent styling pass |

## Acceptance Criteria

1. [ ] App compiles and runs: `make run`
2. [ ] Sidebar: 56px, icon-only, hover/active/checked states, blue left-border indicator
3. [ ] Toolbar: search bar + sort + per-page actions + card-size toggle
4. [ ] Search filters clips in real time; recent searches shown as chips below bar
5. [ ] 3 card sizes toggle visually and update grid layout
6. [ ] Cards render with correct border/radius/metadata/badge/heart/skeleton
7. [ ] Hover: card border brightens, heart icon appears
8. [ ] Processing footer auto-shows when pipeline active, auto-hides when idle
9. [ ] Status bar shows recording indicator + hotkey + storage
10. [ ] Player: seek bar, transport overlay, metadata, action buttons
11. [ ] Stats: 4 metric cards, donut chart, bar chart, table
12. [ ] Settings: two-panel dialog, toggles animate, categories navigate
13. [ ] Trash: matches grid styling, Empty Trash action, restore/delete context menu
14. [ ] Recording: pill button, mode pills, hotkey hint, recent cards
15. [ ] Webhooks: table, add button, edit/delete per row
16. [ ] Rich empty states on all pages
17. [ ] Page transitions: 200ms crossfade
18. [ ] Context menu with Play/Share/Download/Delete + More submenu
19. [ ] Heart toggle on cards (on-hover visibility)
20. [ ] All existing tests pass: `make test`
21. [ ] Lint passes: `make lint`
22. [ ] Dark palette consistent across all pages and dialogs

## Files to Modify

- `src/moment/ui/resources.py`
- `src/moment/ui/main_window.py`
- `src/moment/ui/widgets/clip_delegate.py`
- `src/moment/ui/pages/grid_page.py`
- `src/moment/ui/pages/stats_page.py`
- `src/moment/ui/pages/player_page.py`
- `src/moment/ui/pages/trash_page.py`
- `src/moment/ui/pages/recording_page.py`
- `src/moment/ui/pages/webhook_page.py`
- `src/moment/ui/dialogs/settings_dialog.py`
- `src/moment/ui/app.py` (remove grid page toolbar island wiring)

## New Files

**Icons (SVGs) in `src/moment/ui/assets/icons/`:**
- `library.svg`, `record.svg`, `player.svg`, `stats.svg`, `trash.svg`, `webhooks.svg`, `settings.svg`
- `search.svg`, `sort.svg`, `refresh.svg`, `close.svg`
- `view-grid-small.svg`, `view-grid-medium.svg`, `view-grid-large.svg`
- `play.svg`, `pause.svg`, `skip-back.svg`, `skip-forward.svg`, `volume.svg`, `volume-muted.svg`, `fullscreen.svg`, `fullscreen-exit.svg`
- `share.svg`, `download.svg`, `edit.svg`, `delete.svg`, `restore.svg`, `add.svg`, `check.svg`, `more.svg`
- `heart.svg`, `heart-filled.svg`
- `processing.svg`, `error.svg`, `warning.svg`, `info.svg`
- `chevron-down.svg`
- `empty-library.svg`, `empty-trash.svg`, `empty-recording.svg`, `empty-webhook.svg`
