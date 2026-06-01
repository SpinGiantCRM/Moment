# Phase 6: Settings — settings_dialog.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Rewrite the settings dialog: two-panel layout (category nav left + content right), custom toggle switch widget, OnlyOffice form styling.

## Dialog Structure
- QDialog, modal, no help button
- Size: 720×520 default, resizable, min 600×400
- Left panel: 180px, bg `#181818`
- Right panel: fills remaining, bg `#1a1a1a`
- Separator: 1px `#2a2a2a` vertical line
- Bottom button bar: 1px top border `#2a2a2a`, 48px, right-aligned buttons

## Category Nav (left panel)
- QListWidget, styled per QSS
- Categories: General, Recording, Video, Hotkeys, Output, Cloud & Storage, About
- Each item: 20px icon + 13px label, 8px gap, 12px v-pad, 16px h-pad
- Selected: bg `#323232`, white text, icon accent-blue
- Hover: bg `#2a2a2a`
- Optional group headers: "PREFERENCES" in 10px uppercase muted

## Content Panel (right)
- QStackedWidget, one page per category
- Margins: 24px
- Section title: 15px bold --text-primary
- Section divider: 1px `#3d3d3d`, 16px mb
- Form rows: label (120px, right-aligned, 13px) + control (fills)
- Row height: 32px, center-aligned
- Section spacing: 28px

## Categories

### General
Theme (Dark/Light/System dropdown), Interface density (Normal/Compact/Comfortable dropdown), Font (dropdown), Launch on startup (toggle + dropdown for minimize), Minimize to tray (toggle), Language (dropdown)

### Recording
Output directory (text + Browse button), Mode (Game/Desktop/Window dropdown), Capture audio (toggle), Microphone (dropdown devices), FPS (30/60/120/144 dropdown), Resolution (dropdown)

### Video
Encoder (NVENC H.264/NVENC H.265/Software dropdown), Quality slider (low/medium/high/lossless), Format (MP4/MKV/MOV dropdown), Thumbnail quality (dropdown), Enable GPU acceleration (toggle)

### Hotkeys
Table: command label (right) + QKeySequenceEdit (left). Rows: Save clip, Save with replay, Toggle recording, Open overlay

### Output
Auto-upload target (None/Google Drive/rclone dropdown), Naming pattern text input (`{game}_{date}_{time}`), Auto-open after recording (toggle), Keep N clips (spinbox), Storage limit (spinbox + GB unit)

### Cloud & Storage
Connected accounts list, Add account button, Storage bar (8px progress bar), Sync toggles (auto-upload, WiFi only)

### About
Version, License, Check for updates button, credits/links

## Toggle Switch (custom QWidget)
- Size: 44×22, border-radius 11px
- OFF: bg `#444444`, knob left (2px margin)
- ON: bg `#4a9eff`, knob right (2px margin)
- Knob: 18px circle, `#ffffff`, subtle shadow
- Animation: QPropertyAnimation on knob x position, 150ms
- Click toggles; emit `toggled(bool)`

## Bottom Buttons
- Right-aligned, 8px gap
- Cancel: secondary line-style
- Apply: primary filled
- OK: primary filled (closes dialog)
- All: border-radius 3px, 6px 20px, 13px

## Responsive
- Remember size/position via QSettings
- Left panel min-width, right panel flex

## Acceptance
- Two-panel layout renders correctly
- Category nav switches content
- Toggle switch animates on click
- Form controls work and save/load via QSettings
- Apply/OK saves, Cancel discards
- Dialog remembers size
