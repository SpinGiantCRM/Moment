# Phase 0: SVG Icons
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Create all SVG icon files under `src/moment/ui/assets/icons/`. Style: outline, stroke-width 1.5, `currentColor` (fill="none" for most), 24×24 viewBox.

## Sidebar icons (7)
| File | Path description |
|------|-----------------|
| `library.svg` | 3×3 grid of squares — two rows visible, top row filled |
| `record.svg` | Solid circle (filled, no outline), 20px diameter centered |
| `player.svg` | Play triangle pointing right, slightly rounded corners |
| `stats.svg` | Bar chart — 3 bars ascending: short, medium, tall, rounded tops |
| `trash.svg` | Trash bin outline: wider top, narrower bottom, lid line |
| `webhooks.svg` | Link chain link — 2 interlocking chain segments |
| `settings.svg` | Gear with 6 teeth, centered hole |

## Toolbar icons (8)
- `search.svg` — Magnifying glass, 45° angle handle
- `sort.svg` — Two arrows: up & down, vertical alignment
- `view-grid-small.svg` — 3×3 dense grid
- `view-grid-medium.svg` — 2×2 grid
- `view-grid-large.svg` — 1-column list style (stacked horizontal lines)
- `refresh.svg` — Circular arrow, clockwise
- `chevron-down.svg` — Downward-pointing chevron
- `close.svg` — X shape

## Player transport icons (8)
- `play.svg` — Right-pointing triangle
- `pause.svg` — Two vertical bars
- `skip-back.svg` — Triangle pointing left + vertical bar to left
- `skip-forward.svg` — Triangle pointing right + vertical bar to right
- `volume.svg` — Speaker cone with 3 sound wave arcs descending
- `volume-muted.svg` — Speaker cone with X through it
- `fullscreen.svg` — Diagonal arrows pointing outward
- `fullscreen-exit.svg` — Diagonal arrows pointing inward

## Action icons (10)
- `share.svg` — 3 connected nodes (network symbol)
- `download.svg` — Down arrow into a tray
- `edit.svg` — Pencil at 45°
- `delete.svg` — Trash bin (simpler than sidebar)
- `restore.svg` — Curved arrow pointing backward
- `heart.svg` — Heart outline (unfavorited)
- `heart-filled.svg` — Heart filled (favorited)
- `check.svg` — Checkmark
- `add.svg` — Plus sign
- `more.svg` — Three horizontal dots (overflow)

## Status icons (4)
- `processing.svg` — Spinning circle (can use rotation placeholder)
- `error.svg` — Exclamation in circle
- `warning.svg` — Triangle with exclamation
- `info.svg` — Letter "i" in circle

## Empty state icons (4)
- `empty-library.svg` — Generic empty illustration (open folder or empty box)
- `empty-trash.svg` — Trash can with subtle empty marking
- `empty-recording.svg` — Record circle with muted marking
- `empty-webhook.svg` — Broken link or disconnected nodes

## Acceptance
- All SVGs render correctly in a browser
- Files are valid XML, no broken paths
- Each SVG uses `currentColor` for stroke/fill so QSS coloring works
