# Plan: clip-tray — Consolidated Rebuild Plan (OPEN)

**Status:** OPEN  
**Created:** 2026-05-27  
**Supersedes:** `clip-tray-architecture-plan.md`, `clip-tray-polish-plan.md`  
**Target: ~/projects/clip-tray/ (new package, src/clip_tray/ layout)` (new package), replacing monolithic `clip-tray.py`  

---

## 1. Philosophy

**Be Medal-quality on Linux.** Seamless pipeline from recording to shareable URL. Game performance always prioritized. Keyboard-accessible. Beautiful dark UI inspired by ONLYOFFICE Modern Dark — clean, minimal, flat, generous whitespace, floating island toolbars.

**Capture strategy:** Wrap `gpu-screen-recorder` as a thin subprocess controller. Do NOT reimplement screen capture — the Vulkan/Wayland layer is the hardest, most maintenance-heavy part. Invest in the controller, not the capture engine.

---

## 2. Data Model

### 2.1 Clip

```
id: str (UUID)
stem: str                       # filename stem from MKV
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

title: str                      # display name
game: str | None
tags: list[str]
folder: str | None
favorite: bool

status: ClipStatus
error_message: str | None

uploaded_at: datetime | None
r2_url: str | None
r2_path: str | None
copy_count: int
visibility: ClipVisibility      # public | unlisted | private

created_at: datetime
deleted_at: datetime | None     # soft-delete for trash bin
protect_from_retention: bool

clip_type: ClipType             # video | screenshot | imported
source_app: str | None
original_filename: str | None

updated_at: datetime
watched_at: datetime | None
watch_count: int
```

### 2.2 Enums

```python
class ClipStatus(Enum):
    PENDING, ENCODING, DONE, UPLOADING, UPLOADED, ERROR, CORRUPT, QUEUED

class ClipVisibility(Enum):
    PUBLIC = "public"      # on index page
    UNLISTED = "unlisted"  # direct link only
    PRIVATE = "private"    # not accessible remotely

class ClipType(Enum):
    VIDEO, SCREENSHOT, IMPORTED
```

### 2.3 EditProfile

```python
@dataclass
class EditProfile:
    clip_id: str
    trim_start: float | None
    trim_end: float | None
    split_points: list[float]
    segments: list[SegmentEdit]    # per-segment speed/effects
    game_audio_volume: float       # 0.0-2.0
    mic_audio_volume: float        # 0.0-2.0
    filters: list[FilterConfig]    # brightness, contrast, etc.
    overlays: list[OverlayConfig]  # text, image
    merge_source_ids: list[str] | None
    edit_version: int              # increments on each edit
```

### 2.4 Supporting Models

```python
@dataclass
class Bookmark:
    id: str; session_stem: str; offset_seconds: float
    created_at: datetime; label: str | None

@dataclass
class Webhook:
    id: str; url: str; name: str; enabled: bool
    notify_on: list[str]; per_game_filter: list[str] | None
```

### 2.5 Persistence

SQLite at `~/.config/clip-tray/clips.db` (WAL mode):

| Table | Purpose |
|-------|---------|
| `clips` | All Clip fields |
| `edit_profiles` | EditProfile (1:1 with clips) |
| `tags` | Tag definitions |
| `clip_tags` | Junction table |
| `url_history` | (clip_id, url, copied_at) |
| `webhooks` | Webhook configs |
| `webhook_log` | Delivery history |
| `settings` | Key-value config |
| `folders` | Folder definitions |
| `folder_clips` | Junction table |
| `game_profiles` | Per-game recording profiles |
| `bookmarks` | Mid-session bookmark points |
| `pip_cache` | Recent PiP replay segments |

**Migration:** On first launch, read old `clips.json`. Insert all clips into SQLite. Rename old file to `clips.json.bak`. Set `delete_source` and retention days from old config.

---

## 3. Module Architecture

### 3.1 Package Structure

```
~/projects/clip-tray/src/clip_tray/
├── __init__.py
├── __main__.py                  # python3 -m clip_tray → main()
├── main.py                      # QApplication bootstrap, excepthook
│
├── core/                        # Pure business logic (no GUI imports)
│   ├── models.py                # Dataclasses + enums
│   ├── store.py                 # SQLite CRUD + migration
│   ├── config.py                # Settings table read/write
│   ├── pipeline.py              # Task queue, worker pool, game-aware pausing
│   ├── encoder.py               # ffmpeg NVENC command builder
│   ├── uploader.py              # rclone command builder
│   ├── game_monitor.py          # Game detection (/proc + nvidia-smi)
│   ├── watcher.py               # MKV directory watcher
│   ├── thumbnail.py             # Async thumbnail generation
│   ├── corruption.py            # Health checks, corrupt detection, temp cleanup
│   ├── retention.py             # Age-based + disk-space retention
│   ├── recorder_controller.py   # gpu-screen-recorder subprocess manager
│   ├── bookmarker.py            # Mid-session bookmark handling
│   ├── screenshot.py            # Screenshot capture + processing
│   ├── hotkey_daemon.py         # Global hotkeys (SIGRTMIN, X11/Wayland)
│   ├── discord_bot.py           # Discord webhook dispatch
│   ├── noise_suppression.py     # RNNoise on mic track
│   ├── pip_replay.py            # PiP instant replay cache + playback
│   └── import_export.py         # External clip import
│
├── ui/                          # PyQt6 GUI
│   ├── app.py                   # AppManager: tray + window + lifecycle
│   ├── main_window.py           # QMainWindow with QStackedWidget
│   ├── pages/
│   │   ├── grid_page.py         # Clip library (IconMode, ClipDelegate)
│   │   ├── player_page.py       # Playback + audio mix + URL bar
│   │   ├── stats_page.py        # Dashboard
│   │   ├── trash_page.py        # Recently deleted / trash bin
│   │   └── webhook_page.py      # Discord webhook config
│   ├── dialogs/
│   │   ├── trim_dialog.py       # Dual-handle timeline trim
│   │   ├── settings_dialog.py   # Tabbed settings
│   │   ├── tag_dialog.py        # Tag management
│   │   ├── merge_dialog.py      # Clip selection for merge
│   │   ├── import_dialog.py     # External clip import
│   │   └── game_profile_dialog.py
│   ├── widgets/
│   │   ├── hover_preview.py     # Hover preview popup
│   │   ├── toast.py             # Styled toast manager
│   │   ├── context_menu.py      # Right-click menu builder
│   │   ├── clip_delegate.py     # Custom grid card renderer
│   │   ├── search_bar.py        # Filter search
│   │   ├── processing_banner.py # Status during encode/upload
│   │   ├── pip_window.py        # PiP floating window
│   │   ├── audio_mixer.py       # Per-track audio sliders
│   │   ├── timeline_editor.py   # Split/trim/speed widget
│   │   └── transition_picker.py
│   ├── tray.py                  # System tray icon + menu
│   └── resources.py             # Icons, colors, shared stylesheet
│
└── utils/
    ├── ffmpeg.py                # ffmpeg/ffprobe subprocess wrappers
    └── system.py                # Disk space, symlinks, local IP, OS info
```

### 3.2 Data Flow

```
gpu-screen-recorder → MKV at ~/Videos/
    │
    ▼
Watcher (core/watcher.py)
    │ Detects new MKV via mtime scan (10s interval)
    │ Inserts Clip into store
    │ Emits: clip_discovered(stem)
    ▼
Pipeline (core/pipeline.py)
    │ Thumbnail thread (parallel, priority=low)
    │ Encode thread (serial, GPU-bound, paused during game)
    │ Upload tasks (parallel subprocess, runs during game)
    │
    │ 1. ffprobe metadata
    │ 2. Generate thumbnail (async)
    │ 3. Apply EditProfile → ffmpeg NVENC
    │ 4. rclone copy to R2
    │ 5. Mark uploaded, emit signal
    ▼
GUI (ui/)
    │ GridPage re-populates on signals
    │ Toast on events (batched, not per-clip)
    │ Tray tooltip updates
    │ Clipboard gets URL
```

### 3.3 Threading Model

| Thread | Work | GPU | Paused During Game |
|--------|------|-----|-------------------|
| Main (GUI) | Qt event loop, signals | No | No |
| Encode | 1× ffmpeg NVENC at a time | Yes | Yes |
| Upload | N× rclone concurrent (subprocess) | No | No |
| Thumbnail | 1× at a time (QLowEnergy?) | Yes | Yes |
| Game monitor | /proc scan (2s → 3s timer) | No | No |
| Watcher | mtime scan (5s → 10s timer) | No | No |
| Health check | Every 120s | No | No (skip if pipeline active) |

**GPU semaphore:** Only one ffmpeg process using NVENC at any time. Enforce via `threading.BoundedSemaphore(1)` in `core/encoder.py`.

### 3.4 Game Detection (core/game_monitor.py)

- `/proc` scan for known game processes (configurable list of binary names)
- `nvidia-smi` GPU utilization spike (secondary check, optional)
- KDE D-Bus for fullscreen window detection (future)
- Falls back to: any window with GL context → likely a game
- States: IDLE → GAME_ACTIVE → GAME_EXITING
- On GAME_ACTIVE: pause GPU tasks, minimize window if visible
- On GAME_EXITING: resume GPU tasks, prompt for unclipped/untitled clips

---

## 4. Visual Design System (ONLYOFFICE Modern Dark Inspired)

### 4.1 Philosophy

Clean, flat, minimal. No gradients. No unnecessary borders. Generous whitespace. Floating "island" toolbars. Outline icons. Dark but not black — medium charcoal backgrounds with high-contrast text. ONLYOFFICE Modern Dark as reference.

### 4.2 Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-window` | `#3c3c3c` | Main window background (medium charcoal) |
| `--bg-surface` | `#333` | Cards, panels, menus |
| `--bg-elevated` | `#404040` | Hovered cards, toolbars, toolbar islands |
| `--bg-inset` | `#2a2a2a` | Input fields, text areas |
| `--bg-hover` | `#555` | Button/menu item hover highlight |
| `--bg-active` | `#606060` | Button pressed state |
| `--border-window` | `#2a2a2a` | Window frame border |
| `--border-menu` | `#666` | Menu borders, tooltip borders |
| `--border-focus` | `#60a5fa` | Focus ring |
| `--text-primary` | `#d9d9d9` | Body text, headings |
| `--text-secondary` | `#a1a1aa` | Labels, metadata, size text |
| `--text-muted` | `#757575` | Placeholder, disabled |
| `--accent-blue` | `#60a5fa` | Links, selected state, info toasts |
| `--accent-green` | `#4ade80` | Success, uploaded indicator |
| `--accent-orange` | `#fb923c` | Warning, processing |
| `--accent-red` | `#f87171` | Error, corrupt |
| `--overlay-dark` | `rgba(0,0,0,0.55)` | Thumbnail overlay bar |
| `--shadow-float` | `0 2px 6px rgba(0,0,0,0.3)` | Floating islands, dialogs |
| `--shadow-focus` | `0 0 0 2px rgba(96,165,250,0.4)` | Focus ring (replaces border) |

### 4.3 Typography

| Element | Size | Weight | Color |
|---------|------|--------|-------|
| Page title | 15px | 600 | `--text-primary` |
| Card title | 12px | 500 | `--text-primary` |
| Card metadata | 11px | 400 | `--text-secondary` |
| Input text | 13px | 400 | `--text-primary` |
| Button text | 13px | 500 | `--text-primary` |
| Status bar | 11px | 400 | `--text-secondary` |
| Toast title | 13px | 600 | varies |
| Toast body | 12px | 400 | varies |
| Dialog title | 14px | 600 | `--text-primary` |

Font stack: `"Noto Sans", "Segoe UI", system-ui, sans-serif`

### 4.4 ONLYOFFICE-OnlyVisual Design Rules

1. **No borders on toolbar buttons** — flat background-color change for hover/pressed/active states
2. **Floating island toolbars** — button groups in rounded 6px containers with their own `--bg-elevated` background, 8-12px gap between groups, subtle 2px shadow
3. **Minimal card borders** — grid cards have NO border in normal state. Hover: bg shift + shadow lift. Selected: thin `1px #60a5fa` border
4. **Outline icons** — monoline style, ~1.5-2px stroke, 24×24 grid, 78% opacity white, full white on hover
5. **Spacing** — generous. Page margins 16px. Between sections 12px. Between controls 8px. Icon-to-text gap 4px
6. **Flat inputs** — QLineEdit has `--bg-inset` background, `--border-menu` border (not `--border-window`), focus swaps border to `--accent-blue`
7. **Shadows only on floating elements** — dialogs, toolbar islands, tooltips, menus. Never on cards, never on buttons
8. **Window frame** — `--border-window` only around app window. Inner components don't have outer borders

---

## 5. UI Component Specs

### 5.1 ClipDelegate (Grid Card)

Dimensions: 260w × 190h. No border. Background `--bg-surface`.

```
┌─────────────────────┐
│  ┌─────────────────┐│
│  │                 ││
│  │   THUMBNAIL     ││  ← 240×135, 4px radius, centered
│  │   240×135       ││
│  ├─────────────────┤│  ← --overlay-dark bar, 28h
│  │ Clip Name    ⭐ ││  ← white 12px text
│  └─────────────────┘│
│    2:34 • CS2       │  ← --text-secondary, 11px
│    12 MB   ✓        │
└─────────────────────┘
```

**States:** Normal (`--bg-surface`), Hover (`--bg-elevated` + 2px shadow lift), Selected (`#2a3a45` + `1px #60a5fa` border), Loading (skeleton pulse animation).

**Thumbnail status badges** (top-right corner): ✓ green=uploaded, ⟳ spinning=encoding, ⚠ orange=warning, ✗ red=error/corrupt. ★ (bottom-left, orange)=favorite.

**Progress ring** during encode: 48px diameter arc, 3px stroke, animated 0-360° at 30fps.

### 5.2 Grid Page

```
┌─ margin 16px ─────────────────────────────────────────┐
│ Clips        24 clips                     [sort ▼]     │  ← title row
│ [🔍 Filter clips…                            ] [↻]    │  ← toolbar island (floating, 6px radius)
│ [Encoding 2/5…                                        │  ← proc_banner (only when active)
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │
│ │card1 │ │card2 │ │card3 │ │card4 │                  │  ← scrollable grid
│ └──────┘ └──────┘ └──────┘ └──────┘                  │
│ [status bar — "Copied" / "Idle" / game state]          │
└────────────────────────────────────────────────────────┘
```

**Empty state:** "No clips yet — Press F8 in-game to capture your first clip."
**Error state:** "Could not load database" with [Reset Database] [Open Config Folder] buttons.
**Loading state:** Skeleton cards (pulse animation) until data loads.

### 5.3 Player Page

```
┌─ margin 16px ─────────────────────────────────────────┐
│ [← Grid]  Clip Name              [█] [✏] [✂] [🗑]   │  ← island toolbar
├────────────────────────────────────────────────────────┤
│                                                         │
│              ┌────────────────────────────┐            │
│              │                            │            │
│              │     VIDEO PLAYER           │            │
│              │     (QVideoWidget 16:9)    │            │
│              │     min 640×360            │            │
│              └────────────────────────────┘            │
│                                                         │
│   ██████████████████████░░░░░░  2:34 / 5:12            │  ← seek island
│                                                         │
│   🔊 ───────○────── 50%       Game ──○── 100%          │  ← audio island
│                                Mic  ──○──  80%          │
│   CS2  •  45 MB  •  2026-05-27                          │  ← metadata row
│   URL  https://r2…clyZvv                       [Copy]   │  ← URL island
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Fullscreen:** Double-click video → `showFullScreen()`. Hide toolbar. Show overlay controls on hover. Esc to exit.

**Keyboard shortcuts:**
- Space/K: play/pause | Left/Right: -5s/+5s | J/L: -10s/+10s
- Up/Down: volume ±10% | M: mute
- 0-9: seek to N*10%
- F: fullscreen | Esc: exit FS / back to grid
- R: trim dialog | Delete: delete (confirm) | Ctrl+C: copy URL

### 5.4 Trim Dialog

```
┌────────────────────────────────────────────────────────┐
│  Trim: Clip Name                              [×]      │
├────────────────────────────────────────────────────────┤
│                                                         │
│              ┌────────────────────────────┐            │
│              │                            │            │
│              │   VIDEO PREVIEW            │            │
│              │   (QVideoWidget)           │            │
│              └────────────────────────────┘            │
│                                                         │
│   ⟐ ◁ ▶⏸ ▷ ⟐                                          │  ← transport island
│   ┌──[======|===============|======]──┐                │  ← custom dual-handle timeline
│   In: 1:23 ⟡                    Out: 3:45              │
│                                                         │
│   [Mark In]  [Mark Out]  [Preview Trim]                │  ← button island
│                                                         │
│   [Skip]                         [Cancel]  [Apply]     │
└─────────────────────────────────────────────────────────┘
```

Custom dual-handle timeline: Left=blue (`--accent-blue`), Right=orange (`--accent-orange`). Region between handles: semi-transparent blue. Outside: dimmed. Invalid state (crossed handles): both red, Apply disabled.

Keyboard: I=Mark In, O=Mark Out, P=Preview, Space=Play/Pause, Enter=Apply, Esc=Cancel.

### 5.5 HoverPreviewWidget

360×203, `--bg-surface`, no border, 4px radius. Scaled thumbnail (356×199, `KeepAspectRatio` + `SmoothTransformation`). 500ms delay. Above card; below if offscreen. Auto-closes after 5s. `WA_ShowWithoutActivating`.

### 5.6 Settings Dialog

Tabbed layout (General, Encoding, Notifications, Game Detection). Field validation. Factory Reset button. No Apply button — Save saves all tabs.

### 5.7 PiP Replay Window

Floating 320×180 frameless window. Bottom-right corner of primary monitor. Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool. Frame-by-frame QPixmap playback via ffmpeg pipe (not QVideoWidget, to avoid GL contention with fullscreen games). Auto-closes after 30s. Click to dismiss. Click thumbnail → open normal player with that clip.

---

## 6. Toast System

### 6.1 Design

```
┌─ 320px ─────────────────────────────────┐
│ ✓ Upload complete                [×]     │  ← title (colored by type)
│    clip-name.mp4                         │  ← body (--text-primary)
│    https://r2…                           │
└──────────────────────────────────────────┘
```

Stack bottom-right, max 3 visible. Slide-in animation (200ms). Hover pauses auto-dismiss.

### 6.2 Types

| Type | Icon | Title Color | Duration |
|------|------|-------------|----------|
| `success` | ✓ | `#4ade80` | 5s |
| `info` | ℹ | `#60a5fa` | 4s |
| `warning` | ⚠ | `#fb923c` | 6s |
| `error` | ✗ | `#f87171` | 8s |

"URL copied" → 1.5s.

### 6.3 Event → Toast Mapping

| Event | Toast |
|-------|-------|
| Single clip uploaded | success, "Upload complete" |
| Batch upload done | success, "5 clips uploaded" |
| Single encode done | (no toast — processing banner) |
| Batch encode done | success, "5 clips ready" (1 toast for batch) |
| URL copied | success, "Copied!" (1.5s) |
| Encode/upload error | error, description |
| Game ended | info, "Game ended — N clips ready" |
| Low disk space | warning, "Low disk space — {free} remaining" |
| Cleanup done | info, "Cleanup — N files deleted" |

**NOT toasted:** "Game active" (user knows they're gaming), "Clip discovered" (appears in grid silently), single encode progress (banner is enough), "Encoding clip-1.mp4" (no — too noisy).

**Hard errors get a modal dialog:** Only corrupt DB on startup, missing dependencies (ffmpeg/rclone not found on first run), disk full during write.

---

## 7. Performance Specs

### 7.1 Startup Time

**Target:** <500ms from launch to window visible.

- Show window frame immediately (empty), populate grid asynchronously
- Store loads in <50ms for 500 clips (SQLite WAL mode, indexed queries)
- Thumbnails load on scroll, not on app start
- Pipeline starts AFTER window is visible (defer 500ms)

### 7.2 Memory Budget

| Area | Budget |
|------|--------|
| App at rest | <100MB RSS |
| During encode | <200MB RSS |
| Thumbnail LRU cache | 250 items max (~8MB) |
| SQLite | ~2MB for 500 clips (WAL mode) |
| Video player | GPU memory (QVideoWidget manages itself) |
| Temp transcodes | <500MB on disk, cleaned after use |

### 7.3 Timer Reduction

| Timer | Old Interval | New Interval | Rationale |
|-------|-------------|-------------|-----------|
| Game detection | 2s | 3s | Games don't start in <3s |
| Watcher (mtime) | 5s | 10s | MKVs appear, pipeline catches them |
| Health check | 60s | 120s | No need for rapid checks |
| Processing banner update | every encode step | every 3s | Less visual noise |
| Thumbnail retry | immediate | exp backoff: 5s, 30s, 5min | Don't hammer ffmpeg |

### 7.4 Disk I/O

- Batch metadata writes: SQLite transactions, not per-clip
- Thumbnail dedup: don't generate same thumbnail twice concurrently
- Temp cleanup: scan `/tmp/*.h264.mp4` once per hour
- Log rotation: keep 7 days, auto-rotate at 10MB

### 7.5 Threading

- Encode: one at a time (GPU semaphore). Enforced in code, not convention.
- Upload: N concurrent (subprocess pool, no GPU needed)
- Thumbnail: async, priority = visible clips first
- GUI: never blocked. All pipeline work in threads. Signals for progress.

---

## 8. Pipeline Architecture

### 8.1 Task Types

```python
@dataclass
class Task:
    id: str
    type: Literal["encode", "upload", "thumbnail"]
    priority: int                    # 0=encode, 1=upload, 2=thumbnail
    payload: dict
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 2
```

### 8.2 Game-Aware Pausing

| Game State | Encode | Upload | Thumbnail | Watcher |
|-----------|--------|--------|-----------|---------|
| IDLE | Running | Running | Running | Running |
| GAME_ACTIVE | Paused | Running | Paused | Running (continue discovering) |
| GAME_EXITING | Resume | Running | Resume | Running |

Manual operations (re-trim, re-encode from UI) have a "process now" override flag that runs even during game.

### 8.3 Encode Command Builder

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

### 8.4 Upload Command

```
rclone copy {mp4} {remote}:{bucket}/
```

On re-upload: `rclone delete {remote}:{bucket}/{path}` then `rclone copy`.

---

## 9. Capture Controller (core/recorder_controller.py)

Wraps `gpu-screen-recorder` as managed subprocess. Does NOT reimplement capture.

| Feature | Implementation |
|---------|---------------|
| Per-game profiles | Store in `game_profiles` DB table. On game detect: kill old process, spawn with new params |
| Replay buffer | gpu-screen-recorder `--replay-buffer N` flag |
| Bookmarks | SIGRTMIN saves replay + writes Bookmark to DB |
| Screenshots | SIGUSR1 to gpu-screen-recorder, or ffmpeg x11grab fallback |
| Desktop recording | gpu-screen-recorder `--record-desktop` flag |
| Multiple hotkey durations | Multiple SIGRTMIN signals: F8=30s, F9=60s, F10=300s |
| Audio routing | gpu-screen-recorder `--audio` flags per track |

**Fallback:** If gpu-screen-recorder unavailable, use ffmpeg x11grab + alsa (basic, no replay buffer).

---

## 10. Hotkey Daemon (core/hotkey_daemon.py)

| Backend | Platform |
|---------|----------|
| gpu-screen-recorder SIGRTMIN | Linux (native) |
| python-xlib | X11 |
| KDE D-Bus global shortcuts | KDE Plasma (Wayland) |

**Registered hotkeys:**
- F8: Save 30s replay → bookmark + PiP cache
- F9: Save 60s replay
- F10: Save 5min replay
- Ctrl+F8: Screenshot
- Ctrl+F9: Bookmark timestamp

All configurable in settings.

---

## 11. Notification Reduction Rules

### 11.1 What Gets No Toast

- "Game active — encoding paused" (user knows they're gaming)
- "Clip discovered" (appears silently in grid)
- Single encode progress (processing banner is sufficient)
- "Encoding clip-1.mp4", "Encoding clip-2.mp4" (too noisy — batch into one toast)
- "Uploading clip-1.mp4" (same — batch)

### 11.2 What Gets a Toast

- "Upload complete" (single: per clip; batch: "5 clips uploaded")
- "Encode complete" (ONLY as batch: "5 clips ready")
- "Copied!" (1.5s, quick affirmation)
- Errors (user must know)
- "Game ended — N clips ready"
- "Low disk space" (infrequent, important)
- Cleanup summary

### 11.3 What Gets a Modal Dialog

Only three things, ever:
1. Corrupt DB on startup (with "Reset" + "Open Folder" buttons)
2. Missing ffmpeg/rclone on first run (with install instructions)
3. Disk full during critical write (store can't save)

Everything else = toast.

---

## 12. Error & Recovery

| Component | Error | Behavior |
|-----------|-------|----------|
| Store | DB corrupt | Error state in grid, "Reset Database" button |
| Pipeline | ffmpeg missing | Toast + tray notification |
| Pipeline | rclone missing | Toast + tray notification |
| Pipeline | NVENC unavailable | Fallback to software encode (warning toast) |
| Player | File missing | "Clip file missing — re-encode from source?" overlay |
| Player | Codec unsupported | Transcode to H264 automatically (info toast) |
| Upload | R2 connection failed | Error toast, 3 retries with backoff |
| Upload | Rate limited | Error toast, retry in 60s |
| Settings | Invalid webhook URL | Inline red border |
| Settings | Bad rclone remote | Save-time validation error |

**Unhandled exceptions:**

```python
def excepthook(exc_type, exc_value, exc_tb):
    logging.critical("Unhandled", exc_info=(exc_type, exc_value, exc_tb))
    msg = QMessageBox(QMessageBox.Icon.Critical, "clip-tray Error", str(exc_value))
    msg.setDetailedText(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    msg.exec()
```

---

## 13. Old Script Replacement

### 13.1 Cutover Criteria (ALL must pass)

1. App launches, shows tray icon, window opens
2. Migrates `clips.json` to SQLite
3. Shows all existing clips in grid with thumbnails
4. Plays video in player page
5. Pipeline encodes (NVENC) → uploads (R2) → copies URL to clipboard
6. Game detection pauses/resumes pipeline
7. Trim dialog works, rename works
8. Right-click context menu works (Copy URL, Rename, Delete, Open Folder)
9. Hover preview works
10. Settings saves and loads
11. Close-to-tray works

### 13.2 Cutover Procedure

1. `rm /home/chasem/.local/bin/clip-tray.py`
2. `clip-tray` command resolves to pyproject entry point (`__main__.py`)
3. Old `clips.json` already migrated (renamed to `.bak`)
4. Remove migration code from Store (simplify on delete)
5. `.bak` can be manually deleted after 30 days

**Safety:** Old script writes `clips.json`, new app writes `clips.db`. If old script runs after migration: creates fresh empty `clips.json` (divergent, no data loss). `.bak` is never deleted by the app.

---

## 14. Implementation Phases

### Phase 0: Foundation (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 0.1 | Package scaffold (`__init__.py`, `__main__.py`, `main.py`, `pyproject.toml`) |
| 0.2 | `utils/ffmpeg.py` — ffprobe/ffmpeg wrappers |
| 0.3 | `utils/system.py` — system helpers |
| 0.4 | `core/models.py` — all dataclasses + enums |
| 0.5 | `core/store.py` — SQLite CRUD + migration from old JSON |
| 0.6 | `core/config.py` — settings table management |
| 0.7 | Tests for all above (`pytest`) |

**Verification:** `pip install -e .` → `clip-tray --help` works. Tests pass.

### Phase 1: Core Pipeline (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 1.1 | `core/pipeline.py` — task queue with game-aware pausing |
| 1.2 | `core/encoder.py` — ffmpeg NVENC command builder |
| 1.3 | `core/uploader.py` — rclone command builder |
| 1.4 | `core/game_monitor.py` — game detection (proc + nvidia-smi) |
| 1.5 | `core/watcher.py` — MKV discovery via mtime scan |
| 1.6 | `core/thumbnail.py` — async thumbnail gen + LRU cache |
| 1.7 | `core/corruption.py` — health check, corrupt detection, temp cleanup |

**Verification:** Headless pipeline can encode a sample MKV and upload to R2.

### Phase 2: GUI Skeleton (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 2.1 | `ui/resources.py` — QSS stylesheet, color tokens, icon helpers |
| 2.2 | `ui/app.py` — AppManager: tray + window lifecycle |
| 2.3 | `ui/tray.py` — tray icon + menu + dynamic tooltip |
| 2.4 | `ui/main_window.py` — QMainWindow, stacked widget, toolbar, status bar |
| 2.5 | `ui/pages/grid_page.py` — QListWidget IconMode + ClipDelegate |
| 2.6 | `ui/pages/player_page.py` — QVideoWidget + seek + audio + URL |
| 2.7 | `ui/widgets/hover_preview.py` — HoverPreviewWidget |
| 2.8 | `ui/widgets/toast.py` — ToastManager |
| 2.9 | `ui/widgets/context_menu.py` — right-click menu builder |
| 2.10 | `ui/widgets/search_bar.py` — filter bar with debounce |
| 2.11 | `ui/dialogs/settings_dialog.py` — tabbed settings |

**Verification:** App launches, shows all 20 migrated clips, hover/play/rename/delete work. Toasts appear on events.

### Phase 3: Editing (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 3.1 | `ui/dialogs/trim_dialog.py` — dual-handle timeline trim |
| 3.2 | Trim → re-encode → re-upload flow |
| 3.3 | Edit profile data model integration into pipeline |
| 3.4 | Audio mixer in player page (per-track volume sliders) |

**Verification:** Trim a clip, see re-encode + re-upload. Audio tracks independently adjustable.

### Phase 4: Organization (Est. 1-2 sessions)

| Unit | Deliverable |
|------|------------|
| 4.1 | Tags + folders in store + UI |
| 4.2 | Favorites star in ClipDelegate |
| 4.3 | Multi-select + batch operations |
| 4.4 | `ui/pages/stats_page.py` — dashboard |
| 4.5 | `core/retention.py` — age + disk-space retention |

**Verification:** Tag clips, filter by tag, favorite, batch delete. Retention deletes old files.

### Phase 5: Capture Controller (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 5.1 | `core/recorder_controller.py` — gpu-screen-recorder subprocess mgmt |
| 5.2 | `core/hotkey_daemon.py` — global hotkeys (SIGRTMIN + X11) |
| 5.3 | `core/bookmarker.py` — bookmark handling + auto-trim points |
| 5.4 | `core/screenshot.py` — screenshot capture |
| 5.5 | `ui/dialogs/game_profile_dialog.py` — per-game recording profiles |
| 5.6 | `core/noise_suppression.py` — RNNoise on mic track |

**Verification:** gpu-screen-recorder auto-starts/stops with games. Bookmarks create auto-trimmed clips. Screenshots appear in library. Noise suppression works on mic track.

### Phase 6: PiP + Discord + Trash (Est. 2-3 sessions)

| Unit | Deliverable |
|------|------------|
| 6.1 | `core/pip_replay.py` + `ui/widgets/pip_window.py` — PiP replay |
| 6.2 | `core/discord_bot.py` — Discord webhook dispatch |
| 6.3 | `ui/pages/webhook_page.py` — webhook config UI |
| 6.4 | `ui/pages/trash_page.py` — soft-delete + recovery |
| 6.5 | `core/import_export.py` + `ui/dialogs/import_dialog.py` |

**Verification:** PiP window appears mid-game. Discord webhook posts clip links. Trash bin recovers deleted clips. Import external .mp4 works.

### Phase 7: Editor Enhancements (Est. 3-4 sessions)

| Unit | Deliverable |
|------|------------|
| 7.1 | `ui/widgets/timeline_editor.py` — split/speed timeline |
| 7.2 | Full editor dialog (overlays, filters, chroma key) |
| 7.3 | `ui/dialogs/merge_dialog.py` — multi-clip merge + transitions |
| 7.4 | AV1 NVENC support (config toggle) |
| 7.5 | Ken Burns effect, crop/rotate |
| 7.6 | Built-in music + GIF insertion |

**Verification:** Full editing suite. Timelines, overlays, transitions. AV1 encoding.

---

## 15. Testing

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | `pytest` | Models, store, config, encoder command building, uploader commands |
| Integration | Manual | Full pipeline (encode → upload), game detection, trim flow |
| UI | Manual | Window behavior, toasts, keyboard shortcuts, visual correctness (compare to specs above) |
| Migration | `pytest` | Old JSON → SQLite, edge cases (empty, corrupt, missing files) |

---

## 16. Risks

| Risk | Mitigation |
|------|-----------|
| QMediaPlayer Linux support spotty | H264 tested OK. HEVC transcode to H264. PiP uses QPixmap frames, not QVideoWidget. |
| PiP conflicts with fullscreen GL context | Frame-by-frame QPixmap (ffmpeg pipe), not QVideoWidget. Test on Vulkan games. |
| Wayland global hotkeys limited | KDE D-Bus API; XWayland fallback. Document as "best-effort on Wayland" for initial release. |
| Discord webhook URL leaks | Stored locally only. No server. Revocable via Discord settings. |
| RNNoise quality varies by mic | Bundle cf-librispeech model. Allow per-clip disable. Future: custom model paths. |
| gpu-screen-recorder SIGRTMIN unreliable | Manual bookmark fallback. Test with latest version. |
| GPU contention during encode | Single-thread semaphore. Encode paused during game. RTX 4080 NVENC is fast (<30s per 5min clip). |
| Migration failure | `clips.json` renamed to `.bak`, never deleted. Full rollback: rename back, delete `clips.db`. |

---

## 17. Next Steps

1. Review and approve this consolidated plan
2. Begin Phase 0: Foundation (package scaffold, utils, models, store, migration)
3. Iterate: each phase builds on the previous
4. At Phase 2 completion: cutover from old script (delete `clip-tray.py`)
5. Continue through remaining phases
