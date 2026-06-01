# Phase 7: Remaining Pages — trash, recording, webhook + app.py cleanup
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Apply consistent styling to trash_page.py, recording_page.py, webhook_page.py. Minor cleanup in app.py.

---

## trash_page.py

### Layout
- Same grid card rendering as GridPage (uses same ClipDelegate)
- Same card-size toggle (inherited from main toolbar)
- Same grid margins and spacing (16px, density-aware)
- No search bar (Library only)
- No sort (always sorted by deletion date descending)

### Trash-specific differences
- Toolbar action: "Empty Trash" (danger button, right side of toolbar)
- Context menu: Restore, Delete Permanently, Properties
- Single left-click: opens player page
- Cards show deletion date instead of recording date in metadata

### Empty state
- "Trash is empty" icon + message + CTA "Go to Library" (secondary button)

---

## recording_page.py

### Layout
- Centered content, max 480px wide

### Record Button
- Large pill: 120×48px, border-radius 24px
- Idle: bg `#4a9eff`, text "Start Recording"
- Recording: bg `#f87171`, pulsing animation (opacity 0.7↔1.0 every 1s via QTimer)

### Status
- Idle: "Ready to record" (13px secondary)
- Recording: "Recording..." + elapsed time (13px, red dot icon)
- Error: error message (13px orange)

### Recording Mode Selector
- 3 pill QPushButtons in exclusive group: Game / Desktop / Window
- `border-radius: 14px`, 28px height
- Inactive: secondary line-style
- Active: filled accent (#4a9eff)

### Hotkey Reminder
- "Press Ctrl+F12 to start/stop" (11px muted) below mode selector

### Last Recordings Strip
- Horizontal scroll of mini cards (120×80) showing last 5 clip thumbnails

### Empty State
- Large record icon
- "No recordings yet"
- "Press Ctrl+F12 or click the button above"
- CTA: "Check your Library" (secondary button)

---

## webhook_page.py

### Layout
- Page title: "Webhooks" (18px bold), 16px margin top
- Subtitle: "Send clip events to external services" (13px secondary)

### Webhook Table (QTableView)
- Columns: Name, URL, Events, Last Triggered, Status (toggle or dot)
- Same styling as stats page table
- Each row: edit (pencil icon) + delete (trash icon) buttons at right

### Add Button
- "Add Webhook" primary filled, top-right

### Empty State
- "No webhooks configured"
- "Add a webhook to receive clip events"
- CTA: "Add Webhook" (primary button)

---

## app.py (minor)

- Remove wiring/instantiation of the grid page toolbar island (the hidden toolbar widget that grid_page previously managed)
- Ensure main window toolbar population on startup

---

## Acceptance
- Trash page uses same card rendering as Library, shows deletion date
- "Empty Trash" appears in toolbar on trash page
- Record page: pill button toggles between idle/recording, mode selector works
- Webhook page: table renders, add button works
- No grid toolbar island remnants in app.py
