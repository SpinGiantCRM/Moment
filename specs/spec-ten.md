# spec-ten: Editor

`ui/editor/` module. Separate editor window for complex edits. Quick edits inline on player page.

Edits auto-saved to `EditProfile` in store. Re-encode always runs immediately (ignores encode timing).

---

## Architecture

```
ui/editor/
├── __init__.py
├── editor_window.py       # QMainWindow for complex edits
├── timeline_panel.py      # Multi-segment timeline
├── filter_panel.py        # Filters + overlays + crop
├── merge_panel.py         # Multi-clip merge timeline
├── music_panel.py         # Background music track
└── gif_exporter.py        # GIF export dialog
```

Player page embeds timeline controls + audio mixer + filter panel inline. "Open in Editor" button opens `EditorWindow`.

## Timeline / Splits / Speed

Multi-segment timeline (custom QPainter widget):
- Horizontal bar with colored segments. Each segment: clip range, duration label, speed badge.
- Split at playhead: S key or button. Creates two segments from split point.
- Per-segment speed: 0.25x / 0.5x / 1x / 1.5x / 2x / 3x / 4x dropdown.
- Drag segment boundary handles to adjust split positions.
- Bookmarks shown as diamond markers on timeline (from `Bookmarker`).
- Trim handles at start and end of full clip (from `TrimDialog` spec).

## Filters

Applies to entire clip or per-segment. Controls in inline panel on player + editor window.

- Brightness: -100 to +100 (slider, default 0)
- Contrast: -100 to +100 (default 0)
- Saturation: 0 to 200 (default 100)
- Hue: -180 to +180 (default 0)
- Before/After toggle: side-by-side or A/B split view
- Applied at re-encode via ffmpeg filter chain: `eq=brightness=...:contrast=...:saturation=...` + `hue=h=...`

## Overlays

- **Text overlay:** font family picker, size (8-72px), color picker, position (9-grid presets + free drag), start/end timestamps, duration. Preview in player. Rendered via ffmpeg `drawtext` at re-encode.
- **Image overlay:** file picker (.png with transparency), scale slider (10-200%), position (free drag), duration. Rendered via ffmpeg `overlay` filter.

## Crop / Rotate

- **Crop:** draggable rectangle overlay on video (QWidget with mouse tracking). Aspect ratio lock presets: Free / 16:9 / 4:3 / 1:1 / 21:9. Preset size buttons: 1920x1080, 1280x720, 854x480. Applied via ffmpeg `crop` filter.
- **Rotate:** 0° / 90° / 180° / 270° buttons. Flip horizontal / vertical toggles. Applied via ffmpeg `transpose` / `hflip` / `vflip`.

## Merge

Multi-clip merge timeline:
- Add clips from grid (drag or dialog). Reorder by drag.
- Per-gap transition picker (embed `TransitionPicker` from spec-nine).
- Preview: render first 3s of merged output (bg thread).
- Rendered at re-encode via ffmpeg concat + transitions (`xfade` filter).

## Music Track

- File picker: .mp3 / .wav / .flac / .m4a
- Volume slider: 0-200%. Fade-in (0-5s). Fade-out (0-5s).
- Loop toggle (repeat track if shorter than clip).
- Single track per clip. Mixed at re-encode via ffmpeg `amix` filter. Original game audio preserved (can be ducked via audio mixer).

## GIF Export

`GifExporter` dialog:
- Resolution presets: 320p / 480p / 720p / 1080p
- Frame rate: 10 / 15 / 20 / 24 / 30 fps
- Range: full clip or segment selection
- Uses ffmpeg `palettegen` + `paletteuse` for quality:
  ```
  ffmpeg -i {input} -vf "fps={fps},scale={w}:{h}:flags=lanczos,palettegen" palette.png
  ffmpeg -i {input} -i palette.png -lavfi "fps={fps},scale={w}:{h}:flags=lanczos[x];[x][1:v]paletteuse" {output}.gif
  ```
- Output path: user-chosen location or `~/Pictures/Moment/{clip_stem}.gif`
- Progress bar during generation (background thread)
