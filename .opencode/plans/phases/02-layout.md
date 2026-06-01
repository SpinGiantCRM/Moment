# Phase 2: Layout — main_window.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Rewrite `src/moment/ui/main_window.py`: icon-only sidebar, context toolbar, page stack with fade transitions, auto-hide processing footer, always-visible status bar.

## Layout Architecture
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
├─────────────────────────────────────────────────┤
│  Status Bar (24px)                               │
│  ● Recording ready    Ctrl+F12          45/256GB │
└─────────────────────────────────────────────────┘
```

## Sidebar (icon-only, 56px)
- Change `SIDEBAR_W` from 76 → 56
- Replace QPushButton nav → 7x QToolButton (Library, Record, Player, Stats, Trash, Webhooks, Settings)
- Settings at bottom after a stretch spacer + QFrame divider (1px #2a2a2a)
- `setCheckable(True)`, `setAutoExclusive(True)` on nav buttons
- `setObjectName("sidebarBtn")` — QSS handles styling
- `setIcon(load_icon("library", "#a0a0a0"))` — color changes on checked state
- Tooltips: "Library (Ctrl+1)", "Record (Ctrl+2)", etc.
- Click → `nav_clicked.emit(idx)` → `_stack.setCurrentIndex(idx)`
- Settings click → opens settings dialog, doesn't navigate

## Context Toolbar (36px)
- Background #1e1e1e, bottom border 1px #2a2a2a
- Layout L→R:
  1. Search bar: QLineEdit `toolbarSearch`, 200px, placeholder "Search clips...", clearable
  2. Recent search chips (QPushButton, 11px pill #323232) — shown on search focus, session-only list
  3. Sort dropdown: QComboBox, 130px: "Newest" / "Name A-Z" / "Name Z-A" / "Longest" / "Shortest"
  4. Vertical QFrame separator (20px, #3d3d3d)
  5. Page-specific actions: QPushButton `toolbarAction`, filled by `populate_toolbar(actions)`
  6. Spacer stretch
  7. Card-size toggle: 3x QToolButton `cardSizeToggle` as exclusive QButtonGroup (small/medium/large)

## Page Stack
- QStackedWidget `_stack` — contains all 6 page widgets
- On switch: QPropertyAnimation fade (opacity 1→0 old, 0→1 new), 200ms
- Signal: `page_changed(page_index)`
- Processing footer + status bar are OUTSIDE the stack (persistent)

## Processing Footer (auto-hide, 32px)
- QFrame, `objectName "processingFooter"`, above status bar
- Hidden by default (setVisible(False))
- When pipeline task starts: animate height 0→32, 200ms ease-out
- Layout: status icon + label + compact progress bar (4px, 100px) + "N more" badge
- Multiple tasks: show most recent, count badge
- Auto-hide after all tasks complete + 2s delay
- Styling: bg #242424, top border #3d3d3d, pad 12px h

## Status Bar (24px)
- QFrame, always visible
- Left: "● Recording ready" (green dot label), 11px
- Center: "Ctrl+F12 to record a clip", 11px --text-muted
- Right: "45.2 / 256.0 GB used", 11px --text-muted
- bg #181818, top border #2a2a2a

## Signals to expose
- `search_text_changed(str)` → grid page proxy filter
- `sort_changed(int)` → proxy model sort role
- `card_size_changed(int)` → ClipDelegate._card_size
- `populate_toolbar(list[ToolbarAction])` — called by each page on activation

## Acceptance
- Sidebar shows 7 icons, 56px, hover darkens, active has blue left border
- Toolbar search + sort appear; per-page actions swap when navigating
- Page crossfade works (200ms)
- Config footer hidden at startup; appears when pipeline sends a signal
- Status bar shows recording state + storage
- `make run` no errors
