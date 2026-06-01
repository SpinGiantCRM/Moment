# Phase 3: Cards — clip_delegate.py + grid_page.py
Part of [ui-revamp.md](../ui-revamp.md) (total truth). Read that for systemic questions.

## Scope
Redesign clip card rendering with 3 sizes, skeleton loading, hover states, and adjust grid page layout.

## clip_delegate.py

### Class variable `_card_size`
- int: 0=small, 1=medium, 2=large
- `set_card_size(size)` class method called from grid_page

### Card dimensions
| Size | Card | Thumbnail | Metadata row |
|------|------|-----------|-------------|
| Small | 200×136 | 184×104 | 32px |
| Medium | 272×176 | 256×144 | 32px |
| Large | 360×224 | 344×176 | 48px |

### paint() procedure
1. Background: fill rounded rect `#242424`, border-radius 6px
2. Border: 1px `#3d3d3d`, rounded rect outline
3. Thumbnail: rect at top, 4px top radius, 2px bottom radius (use `QPainterPath` with `addRoundedRect` then clip)
4. If thumbnail None/loading: skeleton pulse — `#2a2a2a` base with animated lighter band `#333333` (60px wide, moves L→R via QTimer 16ms, 1.5s cycle)

### Hover state
- Border: `#3d3d3d` → `#555555`
- Heart icon appears (18×18, top-right 6px from edge)
- Not favorited: `heart.svg` stroke #555555
- Favorited: `heart-filled.svg` fill #f87171

### Elements on card (painting order)
```
┌──────────────────────┐
│              [heart] │  ← on hover
│    THUMBNAIL         │
│              [3:42]  │  ← duration badge
├──────────────────────┤
│ Clip Title Here      │  ← 13px bold, elide 1 line
│ Apr 12 · Valorant    │  ← 11px secondary, dot-separated
└──────────────────────┘
```

### Duration badge
- Bottom-right of thumbnail, 4px margin
- Background `rgba(0,0,0,0.8)`, border-radius 3px
- Text: 11px white monospace, "M:SS" or "H:MM:SS"

### Metadata row
- small/medium: 32px, 1 line title + 1 line metadata
- large: 48px, adds file size + resolution on second line
- Padding: 8px h

## grid_page.py

### Changes
1. Remove the hidden toolbar island widget entirely
2. Remove duplicate search/sort widgets (now in main toolbar)
3. Margins: 16px (density-aware via `apply_spacing`)
4. `CARDS_PER_ROW` dynamic: `max(1, (available_width - 12) // (card_width + 12))`
5. Connect signals:
   - `search_text_changed(text)` → proxy filter
   - `sort_changed(index)` → proxy sort role
   - `card_size_changed(size)` → `ClipDelegate.set_card_size(size)`, invalidate delegate, re-layout

### Empty state (0 rows after filter)
- Centered in grid area
- Icon (64×64 `empty-library.svg` in --text-muted)
- Heading: "No clips yet" or "No results found" (18px)
- Description: 13px secondary
- CTA: "Record a clip" (primary) or clear search btn
- Hidden when model has >0 rows

## Acceptance
- 3 card sizes toggle correctly and re-layout grid
- Skeleton animation plays while thumbnail loads
- Hover brightens border + shows heart
- Duration badge renders bottom-right
- Empty state shows when no clips match filter
- Search + sort from toolbar filter/sort the grid
