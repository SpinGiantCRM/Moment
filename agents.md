# clip-tray — Agent Context

## Project Overview

GPU-accelerated clip management pipeline for Linux. Wraps `gpu-screen-recorder` as a thin subprocess controller, encodes via ffmpeg NVENC, uploads to Cloudflare R2 via rclone, and provides a beautiful dark-themed PyQt6 GUI.

**Key philosophy:** Do NOT reimplement screen capture. Invest in the controller, not the capture engine. Wrap gpu-screen-recorder as a managed subprocess.

## Architecture

```
gpu-screen-recorder → MKV at ~/Videos/
    │
    ▼
Watcher (core/watcher.py) — detects new MKVs via mtime scan (10s interval)
    │ Emits: clip_discovered(stem)
    ▼
Pipeline (core/pipeline.py)
    │ 1. ffprobe metadata
    │ 2. Generate thumbnail (async)
    │ 3. Apply EditProfile → ffmpeg NVENC encode
    │ 4. rclone copy to R2
    │ 5. Mark uploaded, emit signal
    ▼
GUI (ui/) — signals update GridPage, Toast on events, Tray tooltip
```

## Package Structure

```
src/clip_tray/
├── __init__.py          # Version
├── __main__.py          # python -m clip_tray → main()
├── main.py              # QApplication bootstrap, excepthook, High DPI
├── core/                # Pure business logic — NO GUI IMPORTS
│   ├── models.py        # Dataclasses + enums (Clip, EditProfile, Bookmark, Webhook)
│   ├── store.py         # SQLite CRUD + migration from old clips.json
│   ├── config.py        # Settings table read/write
│   ├── pipeline.py      # Task queue, worker pool, game-aware pausing
│   ├── encoder.py       # ffmpeg NVENC command builder
│   ├── uploader.py      # rclone command builder
│   ├── game_monitor.py  # Game detection (/proc + nvidia-smi)
│   ├── watcher.py       # MKV directory watcher (mtime scan)
│   ├── thumbnail.py     # Async thumbnail generation + LRU cache
│   ├── corruption.py    # Health checks, corrupt detection, temp cleanup
│   ├── retention.py     # Age-based + disk-space retention
│   ├── recorder_controller.py  # gpu-screen-recorder subprocess manager
│   ├── bookmarker.py    # Mid-session bookmark handling
│   ├── screenshot.py    # Screenshot capture + processing
│   ├── hotkey_daemon.py # Global hotkeys (SIGRTMIN, X11/Wayland)
│   ├── discord_bot.py   # Discord webhook dispatch
│   ├── noise_suppression.py # RNNoise on mic track
│   ├── pip_replay.py    # PiP instant replay cache
│   └── import_export.py # External clip import
├── ui/                  # PyQt6 GUI
│   ├── app.py           # AppManager: tray + window + lifecycle
│   ├── main_window.py   # QMainWindow with QStackedWidget
│   ├── pages/
│   │   ├── grid_page.py      # Clip library (IconMode, ClipDelegate)
│   │   ├── player_page.py    # Playback + audio mix + URL bar
│   │   ├── stats_page.py     # Dashboard
│   │   ├── trash_page.py     # Recently deleted / trash bin
│   │   └── webhook_page.py   # Discord webhook config
│   ├── dialogs/
│   │   ├── trim_dialog.py         # Dual-handle timeline trim
│   │   ├── settings_dialog.py     # Tabbed settings
│   │   ├── tag_dialog.py          # Tag management
│   │   ├── merge_dialog.py        # Clip selection for merge
│   │   ├── import_dialog.py       # External clip import
│   │   └── game_profile_dialog.py # Per-game recording profiles
│   ├── widgets/
│   │   ├── hover_preview.py       # Hover preview popup
│   │   ├── toast.py               # Styled toast manager
│   │   ├── context_menu.py        # Right-click menu builder
│   │   ├── clip_delegate.py       # Custom grid card renderer
│   │   ├── search_bar.py          # Filter search
│   │   ├── processing_banner.py   # Status during encode/upload
│   │   ├── pip_window.py          # PiP floating window
│   │   ├── audio_mixer.py         # Per-track audio sliders
│   │   ├── timeline_editor.py     # Split/trim/speed widget
│   │   └── transition_picker.py   # Transition selection
│   ├── tray.py          # System tray icon + menu
│   └── resources.py     # Icons, colors, shared stylesheet (QSS)
└── utils/
    ├── ffmpeg.py         # ffmpeg/ffprobe subprocess wrappers
    └── system.py         # Disk space, symlinks, local IP, OS info
```

## Threading Model

| Thread | Work | GPU | Paused During Game |
|--------|------|-----|-------------------|
| Main (GUI) | Qt event loop, signals | No | No |
| Encode | 1× ffmpeg NVENC at a time | Yes | Yes |
| Upload | N× rclone concurrent (subprocess) | No | No |
| Thumbnail | 1× at a time | Yes | Yes |
| Game monitor | /proc scan (3s timer) | No | No |
| Watcher | mtime scan (10s timer) | No | No |
| Health check | Every 120s | No | No |

**GPU semaphore:** threading.BoundedSemaphore(1) in core/encoder.py. Only one ffmpeg NVENC process at any time.

## Data Model — Clip

```python
@dataclass
class Clip:
    id: str                    # UUID
    stem: str                  # filename stem from MKV
    source_path: Path
    encoded_path: Path | None
    thumb_path: Path | None
    recorded_at: datetime
    duration: float
    file_size: int
    video_codec: str
    fps: float
    resolution: tuple[int, int]
    has_mic_audio: bool
    has_game_audio: bool
    title: str                 # display name
    game: str | None
    tags: list[str]
    folder: str | None
    favorite: bool
    status: ClipStatus         # PENDING, ENCODING, DONE, UPLOADING, UPLOADED, ERROR, CORRUPT, QUEUED
    error_message: str | None
    uploaded_at: datetime | None
    r2_url: str | None
    r2_path: str | None
    copy_count: int
    visibility: ClipVisibility  # public, unlisted, private
    created_at: datetime
    deleted_at: datetime | None
    protect_from_retention: bool
    clip_type: ClipType         # video, screenshot, imported
    source_app: str | None
    original_filename: str | None
    updated_at: datetime
    watched_at: datetime | None
    watch_count: int
```

## Design System (ONLYOFFICE Modern Dark Inspired)

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| --bg-window | #3c3c3c | Main window background |
| --bg-surface | #333 | Cards, panels, menus |
| --bg-elevated | #404040 | Hovered cards, toolbars |
| --bg-inset | #2a2a2a | Input fields |
| --bg-hover | #555 | Button hover |
| --bg-active | #606060 | Button pressed |
| --border-window | #2a2a2a | Window frame |
| --border-menu | #666 | Menu borders |
| --border-focus | #60a5fa | Focus ring |
| --text-primary | #d9d9d9 | Body text |
| --text-secondary | #a1a1aa | Labels, metadata |
| --text-muted | #757575 | Placeholder |
| --accent-blue | #60a5fa | Links, selected state |
| --accent-green | #4ade80 | Success |
| --accent-orange | #fb923c | Warning |
| --accent-red | #f87171 | Error |
| --overlay-dark | rgba(0,0,0,0.55) | Thumbnail overlay |
| --shadow-float | 0 2px 6px rgba(0,0,0,0.3) | Floating elements |

### Typography

- Font stack: `"Noto Sans", "Segoe UI", system-ui, sans-serif`
- Page titles: 15px, 600 weight
- Card titles: 12px, 500 weight
- Card metadata: 11px, 400 weight
- Input text: 13px, 400 weight
- Button text: 13px, 500 weight

### Design Rules

1. No borders on toolbar buttons — flat background-color change for hover/pressed/active
2. Floating island toolbars — rounded 6px containers with --bg-elevated background, 8-12px gaps, subtle shadow
3. Grid cards have NO border. Hover: bg shift + shadow lift. Selected: thin 1px #60a5fa border
4. Outline icons — monoline, ~1.5-2px stroke, 24×24 grid, 78% opacity white
5. Generous spacing — page margins 16px, between sections 12px, controls 8px
6. Flat inputs — QLineEdit has --bg-inset, --border-menu border, focus swaps to --accent-blue
7. Shadows only on floating elements — dialogs, toolbar islands, tooltips, menus
8. Window frame — only around app window. Inner components don't have outer borders

## Game Detection (core/game_monitor.py)

- /proc scan for known game processes (configurable binary names)
- nvidia-smi GPU utilization spike (secondary check, optional)
- States: IDLE → GAME_ACTIVE → GAME_EXITING
- On GAME_ACTIVE: pause GPU tasks, minimize window
- On GAME_EXITING: resume GPU tasks, prompt for unclipped clips

## Key Constraints

- **NO GUI imports in core/.** Core modules must be pure business logic.
- **GPU semaphore:** threading.BoundedSemaphore(1) in encoder.py.
- **Encode paused during active game.** Upload continues during game.
- **Thumbnails:** laxy loaded on scroll, not at app startup. LRU cache max 250 items.
- **Toasts:** stack bottom-right, max 3 visible, slide-in animation. Types: success (5s), info (4s), warning (6s), error (8s). "Copied!" = 1.5s.
- **Hard errors get modal dialogs:** Only corrupt DB on startup, missing ffmpeg/rclone on first run, disk full during critical write. Everything else = toast.
- **Startup target:** <500ms. Show empty window immediately, populate grid asynchronously.
- **Memory budget:** <100MB RSS at rest, <200MB during encode.

## Persistence

- SQLite at ~/.config/clip-tray/clips.db (WAL mode)
- Migration: on first launch, read old clips.json → SQLite → rename clips.json → clips.json.bak
- Config: settings table in SQLite, key-value pairs

## Data Flow

```
Watcher → Store.insert(clip)
  ↓
Pipeline.enqueue(Task("encode", clip))
  ├─ ffprobe metadata
  ├─ Generate thumbnail (parallel, low priority)
  ├─ Apply EditProfile → ffmpeg NVENC → encoded.mp4
  ├─ rclone copy → R2
  └─ Store.update(status=UPLOADED, r2_url=...)
        ↓
GUI signals → GridPage updates, Toast appears
```

## Constructing ffmpeg NVENC Commands

```
ffmpeg -hwaccel cuda -y
  [-ss {trim_start}]
  -i {source}
  [-t {trim_end - trim_start}]
  -c:v h264_nvenc
  -preset p7 -rc vbr -cq 23 -b:v 12M
  -maxrate 18M -bufsize 24M
  -pix_fmt yuv420p
  [-c:a aac -b:a 96k]
  [-af "volume={game_vol}:volume={mic_vol},amix"]
  {output}.mp4
```

## Constructing rclone Upload Commands

```
rclone copy {mp4} {remote}:{bucket}/
rclone delete {remote}:{bucket}/{path}    # on re-upload
```
