# Phase 4: Player — player_page.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Redesign the player page: video display area, transport controls overlay, seek bar, metadata row, action buttons.

## Layout
- Top: video display (fills available space, min 480p height)
- Below: metadata row + action buttons

## Video Display
- QWidget with QPainter (or QLabel with pixmaps), bg `#0a0a0a`
- Maintain aspect ratio (`Qt.KeepAspectRatio`)

## Transport Controls Overlay
- Semi-transparent bar: full width, 48px, bg `rgba(0,0,0,0.7)`, positioned at bottom of video area
- Visibility: on mouse hover over video + 3s after last interaction; always visible while paused
- Fade: QPropertyAnimation opacity, 200ms
- Centered controls (L→R):
  - Skip back 10s (24×24 white icon)
  - Play/Pause (28×28, icon swaps)
  - Skip forward 10s (24×24)
  - Volume icon (24×24, click toggles mute)
  - Volume slider (80px QSlider, 4px track)
- Fullscreen toggle: right-aligned (24×24)
- All buttons: transparent bg, white icons, hover slight brighten/scale

## Seek Bar
- Position: directly above transport controls, full width, 24px hit area
- Track: 4px line, bg `rgba(255,255,255,0.2)`, progress fill `#4a9eff`
- Thumb: hidden by default, 14px white circle + blue border on hover
- Hover: track expands to 6px
- Click/drag to seek
- Time labels: left = current (12px mono white), right = total (12px mono #a0a0a0)

## Metadata + Actions
- Horizontal layout, 16px margins all around
- Left column:
  - Title: 18px bold --text-primary
  - Row 2: [Game pill badge] · Date · Duration · File size (13px --text-secondary)
- Right column:
  - Share / Download: primary filled button
  - Edit: secondary line-style
  - Delete: danger line-style

## Empty State
- "Select a clip to preview" centered, with icon

## Acceptance
- Video fills container with aspect ratio
- Transport overlay appears on hover, disappears after 3s
- Play/Pause toggles icon and state
- Seek bar shows progress, clickable/draggable
- Metadata renders correctly below video
- Action buttons styled per line-scale pattern
