# Plan: Moment (prev. clip-tray) — Consolidated Rebuild Plan

**Status:** OPEN
**Created:** 2026-05-27
**Supersedes:** `clip-tray-plan.md`, `tray-launcher-spec.md`, `fleshed-out-spec.md`
**Target:** ~/projects/clip-tray/ → final rename to ~/projects/moment/ (see §2)

---

## 1. Philosophy

**Be Medal-quality on Linux.** Seamless pipeline from recording to shareable URL. Game performance always prioritized. Keyboard-accessible. Beautiful dark UI inspired by ONLYOFFICE Modern Dark — clean, minimal, flat, generous whitespace, floating island toolbars.

**Capture strategy:** Wrap `gpu-screen-recorder` as a thin subprocess controller. Do NOT reimplement screen capture — the Vulkan/Wayland layer is the hardest, most maintenance-heavy part. Invest in the controller, not the capture engine.

**Design values:** Clean, flat, minimal. No gradients. No unnecessary borders. Generous whitespace. Floating "island" toolbars. Outline icons. Dark but not black — medium charcoal backgrounds with high-contrast text.

---

## 2. App Naming

### 2.1 Direction: "Moment"

The project is renamed to **"Moment"** (as in capturing gaming moments). This name was selected from options: Clips, Clipdeck, Shutter, Moment. "Moment" captures the emotional intent — preserving fleeting gaming highlights.

### 2.2 Rename Scope

| Scope | Old Name | New Name |
|-------|----------|----------|
| Package name | `clip-tray` | `moment` |
| Binary | `clip-tray` | `moment` |
| Python import | `clip_tray` | `moment` |
| Directory | `src/clip_tray/` | `src/moment/` |
| `.desktop` file | — | `Moment.desktop` |
| Icon file | `clip-tray.svg` | `moment.svg` |
| Config directory | `~/.config/clip-tray/` | `~/.config/moment/` |
| DB path | `~/.config/clip-tray/clips.db` | `~/.config/moment/clips.db` |
| Log path | `~/.local/share/clip-tray.log` | `~/.local/share/moment.log` |
| UI window title | `"Clip Pipeline"` | `"Moment"` |
| Tray tooltip | — | `"Moment — {status}"` |

### 2.3 Rename Implementation Strategy ⚠️

**Do NOT rename during initial implementation.** The rename affects: pyproject.toml, every import path, config/db paths, log paths, binary name, .desktop file, icons, and documentation.

**Recommended approach:**
1. Implement the full app under `clip-tray` first (Phases 0-6)
2. Then, as a final polish pass before release, rename everything to "Moment" in a single atomic commit
3. This spec uses "Moment" as aspirational name; code uses `clip_tray` / `clip-tray` until Phase 8

**Migration path at rename time:**
1. On first launch as "Moment", attempt to read old SQLite at `~/.config/clip-tray/clips.db`
2. If found and non-empty, import all clips into `~/.config/moment/clips.db`
3. If old `clips.json` exists (pre-SQLite), run original JSON → SQLite migration, then rename to `.bak`
4. Symlink: `~/.local/bin/clip-tray` → `moment` (backward compat during transition)

---

## 3. Data Model

### 3.1 Clip

```python
@dataclass
class Clip:
    id: str                                  # UUID
    stem: str                                # filename stem from MKV
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

    title: str                               # display name
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
    visibility: ClipVisibility                # public | unlisted | private

    created_at: datetime
    deleted_at: datetime | None               # soft-delete for trash bin
    protect_from_retention: bool

    clip_type: ClipType                       # video | screenshot | imported
    source_app: str | None
    original_filename: str | None

    updated_at: datetime
    watched_at: datetime | None
    watch_count: int
```

### 3.2 Enums

```python
class ClipStatus(Enum):
    PENDING, ENCODING, DONE, UPLOADING, UPLOADED, ERROR, CORRUPT, QUEUED

class ClipVisibility(Enum):
    PUBLIC = "public"        # on index page
    UNLISTED = "unlisted"    # direct link only
    PRIVATE = "private"      # not accessible remotely

class ClipType(Enum):
    VIDEO, SCREENSHOT, IMPORTED
```

### 3.3 EditProfile

```python
@dataclass
class EditProfile:
    clip_id: str
    trim_start: float | None
    trim_end: float | None
    split_points: list[float]
    segments: list[SegmentEdit]      # per-segment speed/effects
    game_audio_volume: float         # 0.0-2.0
    mic_audio_volume: float          # 0.0-2.0
    filters: list[FilterConfig]      # brightness, contrast, etc.
    overlays: list[OverlayConfig]    # text, image
    merge_source_ids: list[str] | None
    edit_version: int                # increments on each edit
```

### 3.4 Supporting Models

```python
@dataclass
class Bookmark:
    id: str; session_stem: str; offset_seconds: float
    created_at: datetime; label: str | None

@dataclass
class Webhook:
    id: str; url: str; name: str; enabled: bool
    notify_on: list[str]; per_game_filter: list[str] | None

@dataclass
class GameProfile:
    id: str                           # UUID
    game_name: str                    # Binary name (e.g., "cs2")
    display_name: str                 # "Counter-Strike 2"
    replay_duration: int = 30         # Default F8 duration (seconds)
    audio_config: dict | None = None  # gpu-screen-recorder audio flags
    capture_fps: int = 60             # Capture frame rate
    encode_timing: str | None = None  # None = inherit global default
    quality_preset: str | None = None # Override CQ value
    pause_encode: bool = True         # Pause encode during this game
    pause_thumbnail: bool = True      # Pause thumbnail gen during this game
    auto_tag: bool = True             # Auto-tag clips with game name
    auto_open_editor: bool = True     # Open editor on game exit
    review_card: ReviewCardConfig | None = None

@dataclass
class ReviewCardConfig:
    enabled: bool = True
    size: Literal["small", "medium", "large"] = "medium"
    preview_duration: float = 15.0    # seconds (5-60)
    show_game_name: bool = True
    show_duration: bool = True
    show_file_size: bool = True
    show_quality_badge: bool = True
    show_rename: bool = True
    show_trim: bool = True
    show_favorite: bool = True
    animation_style: Literal["slide", "fade", "scale"] = "slide"
```

### 3.5 Persistence

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
| `settings` | Key-value config (includes encode_timing global default) |
| `folders` | Folder definitions |
| `folder_clips` | Junction table |
| `game_profiles` | Per-game recording profiles (full GameProfile dataclass) |
| `bookmarks` | Mid-session bookmark points |
| `pip_cache` | Recent PiP replay segments |

**Migration (first launch):** Read old `clips.json`. Insert all clips into SQLite. Rename old file to `clips.json.bak`. Set `delete_source` and retention days from old config.

---

## 4. Module Architecture

### 4.1 Package Structure

```
~/projects/clip-tray/src/clip_tray/
├── __init__.py
├── __main__.py                  # python3 -m clip_tray → main()
├── main.py                      # QApplication bootstrap, excepthook, CLI flags
│
├── core/                        # Pure business logic (no GUI imports)
│   ├── models.py                # Dataclasses + enums (all of §3)
│   ├── store.py                 # SQLite CRUD + migration
│   ├── config.py                # Settings table read/write + autostart file mgmt
│   ├── pipeline.py              # Task queue, worker pool, game-aware pausing, encode timing
│   ├── encoder.py               # ffmpeg NVENC command builder
│   ├── uploader.py              # rclone command builder
│   ├── game_monitor.py          # Game detection (/proc + nvidia-smi)
│   ├── watcher.py               # MKV directory watcher
│   ├── thumbnail.py             # Async thumbnail generation
│   ├── corruption.py            # Health checks, corrupt detection, temp cleanup
│   ├── retention.py             # Age-based + disk-space retention (3mo/3yr/8GB)
│   ├── recorder_controller.py   # gpu-screen-recorder subprocess manager
│   ├── bookmarker.py            # Mid-session bookmark handling + trim points
│   ├── screenshot.py            # Screenshot capture + processing
│   ├── hotkey_daemon.py         # Global hotkeys (SIGRTMIN, X11/Wayland/D-Bus)
│   ├── discord_bot.py           # Discord webhook dispatch
│   ├── noise_suppression.py     # RNNoise on mic track
│   ├── pip_replay.py            # PiP instant replay cache + playback
│   ├── import_export.py         # External clip import + batch export
│   └── game_profiles.py         # Per-game profile CRUD + config merge
│
├── ui/                          # PyQt6 GUI
│   ├── app.py                   # AppManager: tray + window + lifecycle + CLI flags
│   ├── main_window.py           # QMainWindow with QStackedWidget
│   ├── tray.py                  # System tray icon + menu + dynamic tooltip
│   ├── resources.py             # Icons, colors, shared stylesheet
│   ├── pages/
│   │   ├── grid_page.py         # Clip library (IconMode, ClipDelegate, batch ops)
│   │   ├── player_page.py       # Playback + audio mix + URL bar
│   │   ├── stats_page.py        # Dashboard (donut chart, bar chart, metrics)
│   │   ├── trash_page.py        # Recently deleted / trash bin
│   │   └── webhook_page.py      # Discord webhook config
│   ├── dialogs/
│   │   ├── trim_dialog.py       # Dual-handle timeline trim
│   │   ├── settings_dialog.py   # Tabbed settings (4 tabs, §6.6)
│   │   ├── tag_dialog.py        # Tag management
│   │   ├── merge_dialog.py      # Clip selection for merge
│   │   ├── import_dialog.py     # External clip import
│   │   └── game_profile_dialog.py # Per-game profile editor (§18)
│   └── widgets/
│       ├── hover_preview.py     # Hover preview popup
│       ├── toast.py             # Styled toast manager
│       ├── review_card.py       # Clip Review Card (15s silent preview popup)
│       ├── context_menu.py      # Right-click menu builder
│       ├── clip_delegate.py     # Custom grid card renderer
│       ├── search_bar.py        # Filter search
│       ├── processing_banner.py # Status during encode/upload
│       ├── progress_ring.py     # Spinning indeterminate arc during encode
│       ├── skeleton_card.py     # Pulse-animated skeleton placeholder
│       ├── pip_window.py        # PiP floating window
│       ├── audio_mixer.py       # Per-track audio sliders
│       ├── timeline_editor.py   # Split/trim/speed widget
│       └── transition_picker.py # Crossfade/whip transition selector
│
└── utils/
    ├── ffmpeg.py                # ffmpeg/ffprobe subprocess wrappers
    ├── system.py                # Disk space, symlinks, local IP, OS info
    └── logging.py               # File + journald logging, rotation
```

### 4.2 Data Flow

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
    │ Encode thread (serial, GPU-bound, respects encode timing)
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
    │ Clip Review Card pops up on capture (source MKV, last 15s silent)
    │ Toast on events (batched, not per-clip)
    │ Tray tooltip updates
    │ Clipboard gets URL
```

### 4.3 Threading Model

| Thread | Work | GPU | Paused During Game |
|--------|------|-----|-------------------|
| Main (GUI) | Qt event loop, signals | No | No |
| Encode | 1× ffmpeg NVENC at a time | Yes | Yes (configurable per-game) |
| Upload | N× rclone concurrent (subprocess) | No | No |
| Thumbnail | 1× at a time | Yes | Yes (configurable per-game) |
| Game monitor | /proc scan (3s timer) | No | No |
| Watcher | mtime scan (10s timer) | No | No |
| Health check | Every 120s | No | No (skip if pipeline active) |

**GPU semaphore:** Only one ffmpeg process using NVENC at any time. Enforce via `threading.BoundedSemaphore(1)` in `core/encoder.py`.

### 4.4 Game Detection (core/game_monitor.py)

- `/proc` scan for known game processes (configurable list of binary names)
- `nvidia-smi` GPU utilization spike (secondary check, optional)
- KDE D-Bus for fullscreen window detection (future, acknowledged gap)
- Falls back to: any window with GL context → likely a game
- States: IDLE → GAME_ACTIVE → GAME_EXITING
- On GAME_ACTIVE: pause GPU tasks per game profile, minimize window if visible
- On GAME_EXITING: resume GPU tasks, open editor view if new clips exist (see §25)

---

## 5. Visual Design System (ONLYOFFICE Modern Dark Inspired)

### 5.1 Color Palette

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

### 5.2 Typography

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

### 5.3 ONLYOFFICE Design Rules

1. **No borders on toolbar buttons** — flat background-color change for hover/pressed/active states
2. **Floating island toolbars** — button groups in rounded 6px containers with `--bg-elevated`, 8-12px gap between groups, subtle 2px shadow
3. **Minimal card borders** — grid cards have NO border in normal state. Hover: bg shift + shadow lift. Selected: thin `1px #60a5fa` border
4. **Outline icons** — monoline style, ~1.5-2px stroke, 24×24 grid, 78% opacity white, full white on hover
5. **Spacing** — generous. Page margins 16px. Between sections 12px. Between controls 8px. Icon-to-text gap 4px
6. **Flat inputs** — QLineEdit has `--bg-inset` background, `--border-menu` border, focus swaps to `--accent-blue`
7. **Shadows only on floating elements** — dialogs, toolbar islands, tooltips, menus. Never on cards, never on buttons
8. **Window frame** — `--border-window` only around app window. Inner components don't have outer borders

---

## 6. UI Component Specs

### 6.1 ClipDelegate (Grid Card)

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

**Thumbnail status badges** (top-right corner): ✓ green=uploaded, ⟳ spinning=encoding (via ProgressRing widget), ⚠ orange=warning, ✗ red=error/corrupt. ★ (bottom-left, orange)=favorite.

**ProgressRing** during encode: 48px diameter arc, 3px stroke, animated indeterminate 0-360° at 30fps. Queued: full orange arc. Encoding: spinning blue arc. Done: snap full green, fade out.

### 6.2 Grid Page

```
┌─ margin 16px ─────────────────────────────────────────┐
│ Clips        24 clips                     [sort ▼]     │  ← title row
│ [🔍 Filter clips…                            ] [↻]    │  ← toolbar island (floating, 6px radius)
│ [Encoding 2/5…                                        │  ← processing_banner (only when active)
│ ☐ 3 selected     [Tag] [★] [🗑] […]                   │  ← batch op toolbar (only in select mode)
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │
│ │card1 │ │card2 │ │card3 │ │card4 │                  │  ← scrollable grid
│ └──────┘ └──────┘ └──────┘ └──────┘                  │
│ [status bar — "Copied" / "Idle" / game state]          │
└────────────────────────────────────────────────────────┘
```

**Selection mode:** Toggle via toolbar button or Ctrl+A. Cards show checkbox in top-left. Selected count in toolbar. Esc exits selection mode.

**Empty state:** Centered card with icon, "No clips yet — Press F8 in-game to capture your first clip." with [View Shortcuts] [Capture Settings] buttons.
**Error state:** "Could not load database" with [Reset Database] [Open Config Folder] buttons.
**Loading state:** 8 skeleton cards (pulse animation) until data loads. `SkeletonCard` widget with 1.5s opacity pulse cycle.

**Processing banner:** 28px height, `--bg-surface` background. Text summary + indeterminate bar. Updated every 3s. Dismissible.

### 6.3 Player Page

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

**Empty state (no clip selected):** "🎬 Select a clip to play" — click from grid or right-click menu.

### 6.4 Trim Dialog

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

Custom dual-handle timeline: Left=blue (`--accent-blue`), Right=orange (`--accent-orange`). Region between: semi-transparent blue. Outside: dimmed. Invalid state (crossed handles): both red, Apply disabled.

Keyboard: I=Mark In, O=Mark Out, P=Preview, Space=Play/Pause, Enter=Apply, Esc=Cancel.

### 6.5 HoverPreviewWidget

360×203, `--bg-surface`, no border, 4px radius. Scaled thumbnail (356×199, `KeepAspectRatio` + `SmoothTransformation`). 500ms delay. Above card; below if offscreen. Auto-closes after 5s. `WA_ShowWithoutActivating`.

### 6.6 Settings Dialog

Tabbed layout (4 tabs). Field validation. Factory Reset button. No Apply button — save on tab switch (persisted immediately).

**Tab 1: General**

```
☑ Start on login                          (creates/deletes ~/.config/autostart/)
☑ Minimize to tray on close

── Separator ──

🎬 Default Encode Timing: [As soon as possible  ▼]
   • As soon as possible
   • After game ends
   • When system is idle

(Manual re-encodes always run immediately, regardless of game state.)

── Separator ──

📁 Storage Locations
   Source files:  ~/Videos/Moment/Source/   [Browse]
   Encoded:       ~/Videos/Moment/Encoded/  [Browse]
   Config:        ~/.config/moment/         [Browse]

── Separator ──

[Reset Database]           [Open Config Folder]
```

**Tab 2: Encoding**

```
🎥 Video Encoder
   Codec:  [H.264 NVENC  ▼]  (H.264/H.265/AV1/Software)
   Preset: [P7 (Slowest) ▼]

── Separator ──

📊 Bitrate Controls
   Quality (CQ):  [━━━━━━━━●━━━━━]  23    (0=lossless  51=worst)
   Target bitrate: [━━━━━●━━━━━━━━━]  12 Mbps
   Max bitrate:    [━━━━●━━━━━━━━━━]  18 Mbps

── Separator ──

🎵 Audio
   Audio codec:   [AAC           ▼]
   Audio bitrate: [96 kbps       ▼]  (64-320)
   ☐ Apply noise suppression to mic track

── Separator ──

⚠ Hardware Acceleration
   Current GPU: NVIDIA RTX 4080 (NVENC available)
   ☐ Fallback to software if NVENC unavailable
```

**Tab 3: Notifications**

```
🔔 Toast Notifications
   ☑ Show upload complete toast
   ☑ Show encode complete toast (batch only)
   ☑ Show error toasts
   ☐ Show cleanup toasts
   ☑ Show low disk space warnings

── Separator ──

🃏 Clip Review Cards
   ☑ Show review cards after capture
   Default size:       [Medium           ▼]
   Preview duration:   [15       seconds]  (5-60)
   ☑ Show mini video player
   ☑ Show game name
   ☑ Show duration
   ☑ Show file size
   ☑ Show quality badge
   ☑ Show rename button
   ☑ Show trim button
   ☑ Show favorite button
   Animation style: [Slide  ▼]  (Slide/Fade/Scale)

── Separator ──

🔈 Sound Notifications
   ☐ Play sound on capture complete
   ☐ Play sound on upload complete
   ☐ Play sound on error
```

**Tab 4: Game Detection**

```
🎮 Game Process Detection
   Scan interval: [3  sec]  (1-10)
   Known game processes:
   ┌──────────────────────────────────┐
   │ cs2                              │
   │ rocket-league                    │
   │ eldenring.exe                    │
   │ minecraft                        │
   │ [Add game…]                      │
   └──────────────────────────────────┘
   ☐ Auto-detect new games (nvidia-smi)
   ☐ Also detect via KDE fullscreen check (Wayland)

── Separator ──

🖥 Behavior During Game
   During game:
     • Encode:          [Paused         ▼]
     • Upload:          [Running        ▼]
     • Thumbnail gen:   [Paused         ▼]
     • Watcher:         [Running        ▼]
   ☑ Minimize main window when game starts
   ☐ Show 'Game active' indicator in tray

── Separator ──

🚪 On Game Exit
   ☑ Open editor for new clips
   ☐ Auto-tag clips with game name
   ☑ Minimize to tray after editor closed
   Default editor window size: [━━━━●━━━] 70%  (40-90%)
```

**Dialog behavior:**
- **Factory Reset:** Confirmation dialog. Clears all settings. Does NOT touch clip data.
- **Reset Database:** Danger-styled confirmation. Resets DB schema, re-migrates from backup.

### 6.7 PiP Replay Window

Floating 320×180 frameless window. Bottom-right corner of primary monitor. Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool. Frame-by-frame QPixmap playback via ffmpeg pipe (not QVideoWidget, to avoid GL contention with fullscreen games). Auto-closes after 30s. Click to dismiss. Click thumbnail → open normal player with that clip.

### 6.8 Clip Review Cards

**Trigger:** Auto-popup immediately after gpu-screen-recorder saves a replay. Shows source MKV (not encoded output). Last N seconds (configurable per game, default 15). Silent mini-player.

```
┌──────────────────────────────────────┐
│  ┌──────────────────────────────┐    │
│  │                              │    │  ← Mini video player (no sound)
│  │   LAST 15 SECONDS OF CLIP    │    │     Aspect ratio matches source
│  │                              │    │     4px radius on video area
│  └──────────────────────────────┘    │
│                                      │
│  Counter-Strike 2             2:34   │  ← --text-primary, 12px, 500
│  Just now                      HQ    │  ← --text-secondary, 11px
│                                      │
│  [✏ Rename]  [✂ Trim]  [★ Favorite] │  ← Action buttons (floating island)
│                                      │
└──────────────────────────────────────┘
```

**Sizes:**
| Size | Width | Height | Player |
|------|-------|--------|--------|
| Small | 320px | ~260px | 180px |
| Medium | 420px | ~340px | 236px |
| Large | 520px | ~420px | 292px |

**Position:** Bottom-right of primary monitor, 24px offset. Above toasts. Max 3 visible (4th replaces oldest). 12px gap between stacked cards.

**Animation:** Slide-in 250ms ease-out. Auto-dismiss after 8s (hover pauses timer). Click outside dismisses all. Close ✕ dismisses individual.

**Actions:** ✏ Rename (inline), ✂ Trim (open editor), ★ Favorite (toggle + dismiss), Click video (open player), ✕ Close.

**UI Scaling:** If mini player disabled, card shrinks to info + actions (~80px height). Width stays same. Layout adjusts gracefully.

**Edge cases:**
- Source file deleted → "File not found" placeholder
- Rapid captures → stack, max 3
- Clip shorter than preview → show full clip, "Full clip" badge
- Game active → card uses `WA_ShowWithoutActivating` (no focus steal)
- 0-byte / corrupt file → error state card

### 6.9 Editor View (Post-Game / Full Editing Suite)

Opens after game exit with new clips, or from Trim/Favorite action on a card. Full Phase 7 features available immediately (not deferred).

```
┌────────────────────────────────────────────────────────────┐
│  Session: Counter-Strike 2         3 new clips    [×]      │
├────────────────────────────────────────────────────────────┤
│                                                             │
│              ┌──────────────────────────────┐              │
│              │                              │              │
│              │     VIDEO PREVIEW            │              │
│              │     (source MKV)             │              │  ← 60% height
│              │                              │              │
│              └──────────────────────────────┘              │
│                                                             │
│   ┌─────────[████████████|░ ░ ░ ░ ░ ░]──────────┐         │
│   │  Trim Start          Trim End    0:00/2:34   │         │
│   └──────────────────────────────────────────────┘         │
│                                                             │
│   🔊 Game ──○─────── 100%    🔊 Mic ──○─── 80%              │
│                                                             │
│   ┌─────────────────────────────────────────┐              │
│   │ Clip Name:  [________________________]  │              │
│   │ Game:       [Counter-Strike 2      ▼]  │              │
│   │ Tags:       [clutch] [highlight] [+]   │              │
│   └─────────────────────────────────────────┘              │
│                                                             │
│   [Split] [Speed] [Filters] [Overlays]                      │
│   [Chroma] [Ken Burns] [Crop] [Music] [GIF]                │
│                                                             │
│   [Skip]                    [◀ Prev]  [Next ▶]  [Done]     │
└────────────────────────────────────────────────────────────┘
```

**Editor features (all from day one):**

| Feature | Implementation |
|---------|---------------|
| **Trim** | Custom dual-handle timeline |
| **Split** | Button or S key at playhead. Creates new timeline segment. |
| **Speed** | Per-segment multiplier 0.1x-4x. Dropdown on segment select. |
| **Audio mix** | Game 0-200%, mic 0-200%. Independent mute toggles. |
| **Filters** | Brightness (-100/+100), Contrast (-100/+100), Saturation (0-200), Hue |
| **Overlays** | Text (font, size, position, duration). Image (PNG, scale, position, duration). |
| **Chroma key** | Color picker, tolerance slider, smoothness slider. Preview checkbox. |
| **Merge** | Add clips to merge list. Reorder. Crossfade/whip transitions. |
| **Ken Burns** | Auto-zoom toggle. Start/end scale + position per segment. |
| **Crop/Rotate** | Crop overlay on preview. Rotation 0/90/180/270. |
| **Music** | Background audio file. Volume + fade in/out. |
| **GIF** | Export segment as GIF. Res 320p-1080p. Frame rate selector. |

**Auto-save:** Edits saved to `EditProfile` in store on navigation, on 2s pause, on close. No "Save" button.

**Session navigation:** Next/Prev saves and moves. Skip discards edits on current clip. Done returns to grid.

**Edge cases:**
- User was editing a clip when game ends → prompt: "Finish current or review new?"
- 15+ clips from one session → scroll navigation + batch rename option
- User closes without naming → clips retain auto-generated stems as titles

### 6.10 Stats Dashboard

```
┌─ margin 16px ───────────────────────────────────────────────┐
│ Dashboard                                              [↻]  │
├────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │   Total   │ │  Storage  │ │ Uploads  │ │   This   │      │
│  │   Clips   │ │   Used   │ │   Today  │ │   Week   │      │
│  │   1,234   │ │  45.2 GB │ │    12    │ │    47    │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│                                                               │
│  ┌────────────────────────────────┐ ┌──────────────────────┐ │
│  │ Storage by Game (donut chart)  │ │ Captures Over Time   │ │
│  │ 🟦 CS2             22.4 GB    │ │ (bar chart, 30 days) │ │
│  │ 🟩 Rocket League     8.1 GB    │ │ ██ ████ █ ██████ ███│ │
│  │ 🟧 Minecraft         5.3 GB    │ │ Mon Tue Wed Thu Fri │ │
│  │ 🟨 Elden Ring         3.2 GB    │ └──────────────────────┘ │
│  │ ⬜ Other             6.2 GB    │                          │
│  └────────────────────────────────┘                          │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Recent Uploads (last 10)                             │   │
│  │  CS2 clutch ace_2026-05-27.mp4    2 min ago  ✓      │   │
│  │  RL save of the game_2026-05-27.mp4  5 min ago ✓    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │  Encode  │ │   Top    │ │  Total   │ │  Avg     │      │
│  │  Speed ⚡ │ │   Game   │ │  Upload  │ │  Clip    │      │
│  │  12.3x   │ │   CS2    │ │  8.4 GB  │ │  2:34    │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
└──────────────────────────────────────────────────────────┘
```

**Charts:** Custom QPainter widgets. Donut (drawPie segments, top 5 + "Other"). Bar (30 days, 1px line for empty days). No external charting library.

**Edge cases:** 30+ games → top 5 + "Other". 1-2 days data → thin line for empty bars. Zero clips → full gray donut + "No data yet". No encodes yet → "—" for encode speed.

---

## 7. Toast System

### 7.1 Design

```
┌─ 320px ─────────────────────────────────┐
│ ✓ Upload complete                [×]     │  ← title (colored by type)
│    clip-name.mp4                         │  ← body (--text-primary)
│    https://r2…                           │
└──────────────────────────────────────────┘
```

Stack bottom-right, max 3 visible. Slide-in animation (200ms). Hover pauses auto-dismiss. Z-order below Clip Review Cards.

### 7.2 Types

| Type | Icon | Title Color | Duration |
|------|------|-------------|----------|
| `success` | ✓ | `#4ade80` | 5s |
| `info` | ℹ | `#60a5fa` | 4s |
| `warning` | ⚠ | `#fb923c` | 6s |
| `error` | ✗ | `#f87171` | 8s |

"URL copied" → 1.5s.

### 7.3 Event → Toast Mapping

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

**NOT toasted:** "Game active" (user knows they're gaming), "Clip discovered" (appears in grid silently), single encode progress (banner is enough), "Encoding clip-1.mp4" (no — too noisy). Clip Review Cards replace toasts for capture events.

**Hard errors get a modal dialog:** Only corrupt DB on startup, missing dependencies (ffmpeg/rclone not found on first run), disk full during critical write.

---

## 8. Tray Icon + Desktop Launcher + Autostart

### 8.1 Tray Icon

**New SVG icon** replacing the old clipboard. Direction: capture/record motif (circle/dot) representing a "moment". Monoline outline matching §5.3 design rules. 24×24 grid for tray.

**Single icon, no state variants.** Status conveyed via tooltip text only (no color changes, no badges, no overlays).

**Icon files:**
- Primary: `hicolor/scalable/apps/moment.svg`
- PNGs: 16, 22, 24, 32, 48, 64, 128, 256px for `hicolor/*/apps/moment.png`

### 8.2 Tray Menu

```
─────────────────────
 Moment — Idle        ← Status line (disabled)
─────────────────────
 Open Moment          ← Show/hide main window
─────────────────────
 📹 Save Replay       ← F8 equivalent (disabled if daemon not running)
 📸 Screenshot        ← Ctrl+F8 equivalent
 📌 Bookmark          ← Ctrl+F9 equivalent
─────────────────────
   3 minutes ago      ← Section header (disabled)
 Replay_2026-05-27…   ← Click → copy URL (max 40 chars)
 Replay_2026-05-26…   ← Click → copy URL
─────────────────────
 Settings…            ← Opens Settings dialog
 Quit                 ← Quit application
─────────────────────
```

- Recent clips: 3 most recently uploaded. Only if clips exist. Click copies URL.
- Dynamic items disabled if daemon not running.
- Status line updated in real-time by pipeline signals.

### 8.3 Tray Tooltip

| State | Tooltip Text |
|-------|-------------|
| Idle, no pending work | `"Moment — Idle"` |
| Encoding (single) | `"Moment — Encoding clip-1.mp4"` |
| Uploading (single) | `"Moment — Uploading clip-1.mp4"` |
| Multiple pipeline tasks | `"Moment — 3 clips encoding"` |
| Game active (paused) | `"Moment — Game active (paused)"` |
| Error state | `"Moment — Error: {brief message}"` |
| Upload complete (brief) | `"Moment — Upload complete"` |

### 8.4 Tray Behavior

| Action | Behavior |
|--------|----------|
| **Left-click** | Toggle main window visibility |
| **Left-click (window visible)** | Focus, raise to top |
| **Right-click** | Open context menu |
| **Middle-click** | Copy last clip URL to clipboard *(best-effort — Wayland may not support)* |
| **Close window** | `closeEvent` → hide to tray (default, toggleable via Settings → General "Minimize to tray on close") |
| **App quit** | Only via Quit in tray menu, or SIGTERM |

### 8.5 Desktop Launcher

**File:** `~/.local/share/applications/Moment.desktop`

```ini
[Desktop Entry]
Type=Application
Name=Moment
Comment=Record, encode, and share gaming clips
Exec=moment
Icon=moment
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=true
Actions=Open Encoded Folder;Settings

[Desktop Action Open Encoded Folder]
Name=Open Encoded Folder
Exec=moment --open-encoded

[Desktop Action Settings]
Name=Settings
Exec=moment --settings
```

**Categories:** Utility (primary), AudioVideo (secondary). NOT Game — Moment supports games but isn't a game.

### 8.6 Autostart

**File:** `~/.config/autostart/Moment.desktop`

```ini
[Desktop Entry]
Type=Application
Name=Moment
Exec=moment --minimized
Icon=moment
Terminal=false
Categories=Utility;
X-KDE-autostart-after=plasma-core
StartupNotify=false
```

**Behavior:** Start minimized to tray (no window on login). Pipeline starts immediately. First-launch exception: show window to confirm migration succeeded.

**Toggle in Settings:** "Start on login" checkbox creates/removes the autostart .desktop files. Managed programmatically — simple file write/unlink.

### 8.7 CLI Arguments

| Flag | Behavior |
|------|----------|
| *(none)* | Show window normally |
| `--minimized` | Start with tray only (used by autostart) |
| `--settings` | Open to Settings dialog. App stays running in tray after close. |
| `--open-encoded` | Open encoded clips folder via xdg-open, then exit |
| `--verbose` | Enable DEBUG-level logging to file + stderr |
| `--help` | Show usage and exit |

---

## 9. Pipeline Architecture

### 9.1 Task Types

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

### 9.2 Game-Aware Pausing + Encode Timing

| Game State | Encode | Upload | Thumbnail | Watcher |
|-----------|--------|--------|-----------|---------|
| IDLE | Running* | Running | Running | Running |
| GAME_ACTIVE | Per encode timing setting** | Running | Per game profile | Running |
| GAME_EXITING | Resume | Running | Resume | Running |

**\* Encode timing in IDLE state:** When no game is active, "As soon as possible" is always used regardless of setting.
**\*\* Encode timing when GAME_ACTIVE:**
- **ASAP** — run (ignoring game, if game profile allows — see §8.3 of pipeline, which has been updated to NOT have a "process now" override but instead has per-game encode timing)
- **After game ends** — pause all encode tasks. Resume on GAME_EXITING.
- **When idle** — pause encode tasks. Run only when system idle (no keyboard/mouse for 5+ mins via idle detection). Resume when idle, pause when active.

Per-game profiles override the global encode timing setting:

```python
# In pipeline.py task queue check:
if game_state == GAME_ACTIVE:
    profile = game_profiles.get(game_name)
    timing = profile.encode_timing if profile and profile.encode_timing else config.get("encode_timing", "asap")
    if timing == "after_game":
        skip encode tasks
    elif timing == "when_idle" and not system_is_idle():
        skip encode tasks
```

Manual re-encodes from UI always run immediately (regardless of encode timing setting).

### 9.3 Encode Command Builder

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

### 9.4 Upload Command

```
rclone copy {mp4} {remote}:{bucket}/
```

On re-upload: `rclone delete {remote}:{bucket}/{path}` then `rclone copy`.

---

## 10. Capture Controller (core/recorder_controller.py)

Wraps `gpu-screen-recorder` as managed subprocess. Does NOT reimplement capture.

### 10.1 Subprocess Management

```python
class RecorderController:
    """Manages gpu-screen-recorder as a subprocess."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._current_profile: GameProfile | None = None

    def start_recording(self, profile: GameProfile) -> None:
        """Kill existing, spawn with profile params."""
        self.stop_recording()
        cmd = self._build_command(profile)
        self._process = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Process group for signal sending
        )

    def stop_recording(self) -> None:
        """Send SIGTERM to gpu-screen-recorder."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)

    def save_replay(self, seconds: int = 30) -> None:
        """Send SIGRTMIN(+n) to save replay buffer."""
        if self._process and self._process.poll() is None:
            self._process.send_signal(self._replay_signal(seconds))
            # Also write Bookmark to DB

    def take_screenshot(self) -> None:
        """Send SIGUSR1 to capture screenshot."""
        if self._process and self._process.poll() is None:
            self._process.send_signal(signal.SIGUSR1)
```

### 10.2 SIGRTMIN Signal Mapping

| Action | Signal |
|--------|--------|
| Save 30s replay | `SIGRTMIN` |
| Save 60s replay | `SIGRTMIN + 1` |
| Save 5min replay | `SIGRTMIN + 2` |
| Take screenshot | `SIGUSR1` |

### 10.3 Profile Switching

On `IDLE → GAME_ACTIVE`:
1. Look up game in `game_profiles` table
2. If profile exists with custom params → stop current → start with new params
3. If no profile → continue with default/current params

### 10.4 Feature Table

| Feature | Implementation |
|---------|---------------|
| Per-game profiles | Store in `game_profiles` table. On game detect: kill old, spawn with new params |
| Replay buffer | gpu-screen-recorder `--replay-buffer N` flag |
| Bookmarks | SIGRTMIN saves replay + writes Bookmark to DB |
| Screenshots | SIGUSR1 to gpu-screen-recorder, or ffmpeg x11grab fallback |
| Desktop recording | gpu-screen-recorder `--record-desktop` flag |
| Multiple hotkey durations | Multiple SIGRTMIN signals: F8=30s, F9=60s, F10=300s |
| Audio routing | gpu-screen-recorder `--audio` flags per track (exact flags TBD per gpu-screen-recorder docs) |

**Fallback:** If gpu-screen-recorder unavailable, use ffmpeg x11grab + alsa (basic, no replay buffer).

---

## 11. Hotkey Daemon (core/hotkey_daemon.py)

### 11.1 Backend Selection

```python
class HotkeyDaemon:
    def __init__(self):
        self.backend = self._detect_backend()

    def _detect_backend(self) -> HotkeyBackend:
        """Auto-detect: SIGRTMIN > D-Bus > X11 > fallback."""
        if self._has_gpu_screen_recorder():
            return HotkeyBackend.SIGRTMIN
        elif self._is_kde_plasma():
            return HotkeyBackend.KDE_DBUS
        elif self._is_x11():
            return HotkeyBackend.X11
        return HotkeyBackend.FALLBACK
```

### 11.2 SIGRTMIN Backend (Primary)

- gpu-screen-recorder must be running (managed by `RecorderController`)
- Send signals to the recorder subprocess (not to self)
- No external library needed — `subprocess.send_signal()`

### 11.3 KDE D-Bus Backend

```python
import dbus

bus = dbus.SessionBus()
kglobal = bus.get_object('org.kde.kglobalaccel', '/kglobalaccel')
kglobal_interface = dbus.Interface(kglobal, 'org.kde.KGlobalAccel')

# Register shortcut
action = kglobal_interface.registerShortcut(
    "Moment Save Replay", "Save Replay", "F8",
    "Moment", True
)

# Listen for activated signal
bus.add_signal_receiver(
    self._on_hotkey_activated,
    signal_name="shortcutActivated",
    dbus_interface="org.kde.kglobalaccel",
    path="/kglobalaccel"
)
```

### 11.4 X11 Backend (Fallback)

```python
# Using python-xlib
from Xlib import X, XK
from Xlib.ext import record

ctx = record.RecordContext(display)
ctx.enable_context(True)
# In event loop: listen for KeyPress, match configured keycodes, trigger action
```

### 11.5 Registered Hotkeys

| Hotkey | Action | |
|--------|--------|--|
| F8 | Save 30s replay | Default |
| F9 | Save 60s replay | Default |
| F10 | Save 5min replay | Default |
| Ctrl+F8 | Take screenshot | Default |
| Ctrl+F9 | Bookmark current position | Default |
| *User configurable* | *Any action above* | Settings → Keyboard* |

**\* Keyboard shortcut settings UI is a gap — not yet specified beyond this table.**

---

## 12. Notification Reduction Rules

### 12.1 What Gets No Toast

- "Game active — encoding paused" (user knows they're gaming)
- "Clip discovered" (appears silently in grid)
- Single encode progress (processing banner is sufficient)
- "Encoding clip-1.mp4", "Encoding clip-2.mp4" (too noisy — batch into one toast)
- "Uploading clip-1.mp4" (same — batch)
- Clip capture events (replaced by Clip Review Cards)

### 12.2 What Gets a Toast

- "Upload complete" (single: per clip; batch: "5 clips uploaded")
- "Encode complete" (ONLY as batch: "5 clips ready")
- "Copied!" (1.5s, quick affirmation)
- Errors (user must know)
- "Game ended — N clips ready"
- "Low disk space" (infrequent, important)
- Cleanup summary

### 12.3 What Gets a Modal Dialog

Only three things, ever:
1. Corrupt DB on startup (with "Reset" + "Open Folder" buttons)
2. Missing ffmpeg/rclone on first run (with install instructions)
3. Disk full during critical write (store can't save)

Everything else = toast.

---

## 13. Error & Recovery

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

### 13.1 Corruption Detection (core/corruption.py)

**Health checks (every 120s):**

| Check | Method | Action on Failure |
|-------|--------|-------------------|
| **Disk space** | `shutil.disk_usage()` on home | <5GB: warning toast. <1GB: disable encoding + warning toast |
| **Temp file age** | Scan `/tmp/*.h264.mp4`, mtime > 1hr | Delete stale temps. Log count. |
| **DB integrity** | `PRAGMA integrity_check` | If fails: error toast, "Reset Database" button |
| **Pipeline stuck** | Task PENDING/ENCODING >30min | Mark as ERROR. Notify user. |

**Corrupt detection (per-clip, on discovery):**

| Check | Method | Result |
|-------|--------|--------|
| Zero-byte file | `os.path.getsize()` == 0 | CORRUPT |
| ffprobe probe | Parse ffprobe output | No video stream or duration=0 → CORRUPT |
| Partial write | mtime <30s + size growing | Skip scan cycle, wait for stable |
| Container corrupt | ffmpeg error on first frame decode | CORRUPT |

User actions on CORRUPT: Retry, Delete, Ignore.

### 13.2 Temp Cleanup

- Scan `/tmp/clip-tray-*.mp4` every 120s (during health check)
- Delete files with mtime > 1 hour (orphaned from crashed encodes)
- Log: "Temp cleanup: removed N orphaned files (freed X MB)"

---

## 14. Retention Policy (core/retention.py)

### 14.1 Defaults

| Tier | Retention Rule | Detail |
|------|---------------|--------|
| **Source files** (MKV) | 3 months | Delete >90 days old. Skip if `protect_from_retention=True`. |
| **Encoded files** (MP4) | 3 years | Delete >1095 days old. |
| **Cloud** (R2) | 8GB rolling limit | FIFO: newest replaces oldest when total exceeds 8GB. |
| **YouTube** | Permanent (future) | When YouTube upload added: daily batch upload, clips become permanent there. |

### 14.2 Conflict Resolution

When age and disk-space limits conflict: **most restrictive applies** (keeps fewer clips). User can change this in settings.

### 14.3 Protection

- `protect_from_retention=True` → never deleted by retention rules
- Toggled via clip context menu: "Protect from deletion"
- Protected clips count against disk budgets but are skipped during cleanup

---

## 15. Logging

### 15.1 Strategy

| Destination | Path | Level | Format |
|-------------|------|-------|--------|
| **File** | `~/.local/share/moment/moment.log` | INFO (DEBUG with `--verbose`) | `[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message` |
| **Systemd journal** | via stderr | Same as file | Structured |

### 15.2 Rotation

- Auto-rotate at 10MB (delete old, keep current)
- Keep 7 days of history (`.log.1`, `.log.2` etc.)
- File size checked on each write

### 15.3 Log Levels

| Level | Used for |
|-------|----------|
| ERROR | Pipeline failures, DB errors, unexpected exceptions |
| WARNING | Non-critical: retry attempts, missing deps, config fallbacks |
| INFO | Pipeline state transitions, encode start/end, upload start/end, game state changes |
| DEBUG | FFmpeg command strings, subprocess output, signal emissions, timer ticks |

---

## 16. Bookmark Integration

- **Created by:** hotkey (Ctrl+F9 default) → SIGRTMIN + Bookmark record in DB
- **Stores:** `session_stem`, `offset_seconds`, `label` (optional dialog on creation)
- **In editor:** Bookmarks appear as diamond markers on the timeline
- **Right-click bookmark:** "Set trim start here" / "Set trim end here"
- **Click bookmark:** Jump playhead to position

---

## 17. Batch Operations

### 17.1 Selection Model

- Checkbox mode in grid page (toggle via toolbar or Ctrl+A)
- Selected count: "3 selected"
- Esc to exit selection mode

### 17.2 Operations

| Operation | Behavior |
|-----------|----------|
| **Delete** | Soft-delete to trash. If already in trash, permanently delete. |
| **Add tag** | Dialog: "Add tag to N clips" — text input + existing tags. |
| **Remove tag** | Dialog: "Remove tag from N clips" — list of common tags. |
| **Toggle favorite** | ★/☆ all selected (toggle logic) |
| **Re-encode** | Re-encode with current quality settings. Queues in pipeline. |
| **Re-upload** | Delete old R2 file, upload new. |
| **Move to folder** | Dialog: select or create folder. |
| **Set game** | Dialog: text input with autocomplete. |
| **Export** | Copies encoded MP4s to chosen folder. *(Proposed — may need refinement)* |

### 17.3 Shortcuts

Ctrl+A = select all | Shift+click = range select | Ctrl+click = toggle individual | Esc = exit selection

---

## 18. Game Profiles (core/game_profiles.py + ui/dialogs/game_profile_dialog.py)

### 18.1 Data Model

```python
@dataclass
class GameProfile:
    id: str                           # UUID
    game_name: str                    # Binary name (e.g., "cs2")
    display_name: str                 # "Counter-Strike 2"
    replay_duration: int = 30         # Default F8 duration (seconds)
    audio_config: dict | None = None  # gpu-screen-recorder audio flags
    capture_fps: int = 60             # Capture frame rate
    encode_timing: str | None = None  # None = inherit global default
    quality_preset: str | None = None # Override CQ value
    pause_encode: bool = True         # Pause encode during this game
    pause_thumbnail: bool = True      # Pause thumbnail gen during this game
    auto_tag: bool = True             # Auto-tag clips with game name
    auto_open_editor: bool = True     # Open editor on game exit
    review_card: ReviewCardConfig | None = None
```

### 18.2 Game Profiles Dialog

```
┌──────────────────────────────────────────────────────┐
│  Game Profiles                                [×]    │
├──────────────────────────────────────────────────────┤
│                                                        │
│  ┌──────────────────────────────────────────────┐    │
│  │ cs2                    🔴 Recording    [Edit] │    │
│  │ rocket-league          🟢 Not active   [Edit] │    │
│  │ [+ Add Game Profile]                         │    │
│  └──────────────────────────────────────────────┘    │
│                                                        │
│  ── Editing: Counter-Strike 2 ───────────────────────  │
│                                                        │
│  Display name: [Counter-Strike 2                ]     │
│  Binary name:  [cs2                              ]     │
│                                                        │
│  Recording:                                           │
│  Default replay: [30          ] seconds                │
│  Capture FPS:    [60          ] fps                    │
│                                                        │
│  Pipeline:                                             │
│  Encode timing:  [Inherit (ASAP)              ▼]      │
│  ☑ Pause encode during game                           │
│  ☑ Pause thumbnail during game                        │
│  ☑ Auto-tag with game name                            │
│  ☑ Open editor on game exit                           │
│                                                        │
│  Review Card:                                          │
│  ☑ Show review cards for this game                     │
│  Size:           [Medium                       ▼]     │
│  Preview duration: [15          ] seconds              │
│  ☑ Show mini player                                    │
│  ☑ Show game name                                      │
│  ☑ Show duration                                       │
│  ☑ Show file size                                      │
│                                                        │
│  [Delete Profile]              [Cancel]  [Save]        │
└────────────────────────────────────────────────────────┘
```

---

## 19. Game Exit Flow

### 19.1 Trigger

When `GAME_ACTIVE → GAME_EXITING` with new clips produced:
1. App window opens automatically (if hidden/minimized)
2. Window takes configured size (default 70% of screen, configurable 40-90%)
3. Switches to Editor View showing the first un-named clip from this session
4. User edits + names clips → Next → Next → Done

### 19.2 Conditions

| Condition | Behavior |
|-----------|----------|
| Game exits with new clips | Editor opens, window shown & focused |
| Game exits with NO new clips | Nothing happens. App stays hidden. |
| User actively using app during game exit | Banner: "Game ended — 3 new clips ready [Review Now] [Later]" |
| App open but minimized | Window raised, editor shown |

### 19.3 Auto-Save

Edits auto-saved to `EditProfile` on navigation between clips. No explicit Save button.

---

## 20. Encode Timing Settings

### 20.1 Options

| Setting | Behavior |
|---------|----------|
| **As soon as possible** | Encode starts immediately after thumbnail gen |
| **After game ends** | Encode tasks queued but NOT executed while GAME_ACTIVE. Begin on GAME_EXITING/IDLE. |
| **When system is idle** | Encode only when system idle 5+ mins (no mouse/keyboard/game). Pause on activity. Resume on idle. |

### 20.2 Per-Game Override

Each game profile can override. None = inherit global default. When no game detected, "As soon as possible" is always used.

---

## 21. Performance Specs

### 21.1 Startup Time

**Target:** <500ms from launch to window visible.
- Show window frame immediately (empty), populate grid asynchronously
- Store loads in <50ms for 500 clips (SQLite WAL mode, indexed queries)
- Thumbnails load on scroll, not on app start
- Pipeline starts AFTER window is visible (defer 500ms)

### 21.2 Memory Budget

| Area | Budget |
|------|--------|
| App at rest | <100MB RSS |
| During encode | <200MB RSS |
| Thumbnail LRU cache | 250 items max (~8MB) |
| SQLite | ~2MB for 500 clips (WAL mode) |
| Video player | GPU memory (QVideoWidget manages itself) |
| Temp transcodes | <500MB on disk, cleaned after use |

### 21.3 Timer Reduction

| Timer | Interval | Rationale |
|-------|----------|-----------|
| Game detection | 3s | Games don't start in <3s |
| Watcher (mtime) | 10s | MKVs appear, pipeline catches them |
| Health check | 120s | No need for rapid checks |
| Processing banner update | every 3s | Less visual noise |
| Thumbnail retry | exp backoff: 5s, 30s, 5min | Don't hammer ffmpeg |

### 21.4 Disk I/O

- Batch metadata writes: SQLite transactions, not per-clip
- Thumbnail dedup: don't generate same thumbnail twice concurrently
- Temp cleanup: scan `/tmp/*.h264.mp4` once per hour
- Log rotation: keep 7 days, auto-rotate at 10MB

### 21.5 Threading

- Encode: one at a time (GPU semaphore). Enforced in code, not convention.
- Upload: N concurrent (subprocess pool, no GPU needed)
- Thumbnail: async, priority = visible clips first
- GUI: never blocked. All pipeline work in threads. Signals for progress.

---

## 22. Old Script Replacement

### 22.1 Cutover Criteria (ALL must pass)

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

### 22.2 Cutover Procedure

1. `rm /home/chasem/.local/bin/clip-tray.py`
2. `clip-tray` command resolves to pyproject entry point
3. Old `clips.json` already migrated (renamed to `.bak`)
4. Remove migration code from Store (simplify on delete)
5. `.bak` can be manually deleted after 30 days

**Safety:** Old script writes `clips.json`, new app writes `clips.db`. If old script runs after migration: creates fresh empty `clips.json` (divergent, no data loss). `.bak` is never deleted by the app.

---

## 23. Implementation Phases

### Phase 0: Foundation (Est. 2-3 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 0.1 | Package scaffold (`__init__.py`, `__main__.py`, `main.py`, `pyproject.toml`) | — |
| 0.2 | `utils/ffmpeg.py` — ffprobe/ffmpeg wrappers | — |
| 0.3 | `utils/system.py` — system helpers | — |
| 0.4 | `core/models.py` — all dataclasses + enums (incl. GameProfile, ReviewCardConfig) | §3 |
| 0.5 | `core/store.py` — SQLite CRUD + migration from old JSON | §3.5 |
| 0.6 | `core/config.py` — settings table + autostart file mgmt | §3.5, §8.6 |
| 0.7 | `utils/logging.py` — file + journald logging, rotation | §15 |
| 0.8 | Tests for all above (`pytest`) | — |

**Verification:** `pip install -e .` → `clip-tray --help` works. Tests pass.

### Phase 1: Core Pipeline (Est. 3-4 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 1.1 | `core/pipeline.py` — task queue, game-aware pausing, encode timing | §9 |
| 1.2 | `core/encoder.py` — ffmpeg NVENC command builder | §9.3 |
| 1.3 | `core/uploader.py` — rclone command builder | §9.4 |
| 1.4 | `core/game_monitor.py` — game detection (proc + nvidia-smi) | §4.4 |
| 1.5 | `core/watcher.py` — MKV discovery via mtime scan | — |
| 1.6 | `core/thumbnail.py` — async thumbnail gen + LRU cache | — |
| 1.7 | `core/corruption.py` — health checks, corrupt detection, temp cleanup | §13.1 |
| 1.8 | `core/retention.py` — age-based + disk-space retention (3mo/3yr/8GB) | §14 |

**Verification:** Headless pipeline can encode sample MKV and upload to R2. Retention runs and cleans up.

### Phase 2a: GUI Skeleton (Est. 3-4 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 2.1 | `ui/resources.py` — QSS stylesheet, color tokens, icon helpers | §5 |
| 2.2 | `ui/app.py` — AppManager: tray + window + lifecycle + CLI flags | §8.7 |
| 2.3 | `ui/tray.py` — tray icon + menu + dynamic tooltip | §8 |
| 2.4 | `ui/main_window.py` — QMainWindow, stacked widget, toolbar, status bar | — |
| 2.5 | `ui/pages/grid_page.py` — QListWidget IconMode + ClipDelegate + selection | §6.2 |
| 2.6 | `ui/pages/player_page.py` — QVideoWidget + seek + audio + URL | §6.3 |
| 2.7 | `ui/widgets/hover_preview.py` — HoverPreviewWidget | §6.5 |
| 2.8 | `ui/widgets/toast.py` — ToastManager | §7 |
| 2.9 | `ui/widgets/context_menu.py` — right-click menu builder | — |
| 2.10 | `ui/widgets/search_bar.py` — filter bar with debounce | — |
| 2.11 | `ui/dialogs/settings_dialog.py` — tabbed settings (4 tabs, full per-tab spec) | §6.6 |

**Verification:** App launches, shows all migrated clips in grid, hover/play/rename/delete work. Left-click tray toggles window. Settings saves/loads. Tray tooltip updates.

### Phase 2b: Review Cards, Editor, Game Flow (Est. 3-4 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 2.12 | `ui/widgets/review_card.py` — Clip Review Card (15s silent preview) | §6.8 |
| 2.13 | `core/game_profiles.py` + `ui/dialogs/game_profile_dialog.py` | §18 |
| 2.14 | Game exit flow — auto-open editor view | §19 |
| 2.15 | `ui/dialogs/trim_dialog.py` — dual-handle timeline trim | §6.4 |
| 2.16 | Editor view — post-game editor with full editing features | §6.9 |
| 2.17 | `ui/pages/stats_page.py` — full dashboard with charts | §6.10 |
| 2.18 | Encode timing settings (global + per-game override) | §20 |
| 2.19 | Batch operations in grid page (multi-select, 8 ops) | §17 |

**Verification:** Review card pops up after capture. App opens on game exit with editor. Dashboard shows real metrics. Batch ops work.

### Phase 2c: Widgets, Daemons, Polish (Est. 3-4 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 2.20 | `ui/widgets/skeleton_card.py` — pulse-animated loading placeholder | §6.2 (loading) |
| 2.21 | `ui/widgets/progress_ring.py` — indeterminate encode progress arc | §6.1 |
| 2.22 | `ui/widgets/processing_banner.py` — pipeline status banner | §6.2 |
| 2.23 | Clipboard copying + `--open-encoded` CLI flag | — |
| 2.24 | `moment.svg` icon (SVG + multi-res PNGs) | §8.1 |
| 2.25 | `Moment.desktop` for application launcher + autostart | §8.5, §8.6 |
| 2.26 | Empty states for all pages (grid, player, trash, webhook) | §6.x |

**Verification:** Skeleton shows on load. Progress ring spins during encode. Desktop file launches app. Autostart works.

### Phase 3: Capture Controller + Hotkeys (Est. 2-3 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 3.1 | `core/recorder_controller.py` — gpu-screen-recorder subprocess mgmt | §10 |
| 3.2 | `core/hotkey_daemon.py` — global hotkeys (SIGRTMIN + D-Bus + X11) | §11 |
| 3.3 | `core/bookmarker.py` — bookmark handling + timeline markers | §16 |
| 3.4 | `core/screenshot.py` — screenshot capture | §10.4 |
| 3.5 | `core/noise_suppression.py` — RNNoise on mic track | — |

**Verification:** gpu-screen-recorder auto-starts/stops with games. F8 saves replay. Bookmarks appear in timeline.

### Phase 4: PiP + Discord + Trash (Est. 2-3 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 4.1 | `core/pip_replay.py` + `ui/widgets/pip_window.py` — PiP replay | §6.7 |
| 4.2 | `core/discord_bot.py` — Discord webhook dispatch | — |
| 4.3 | `ui/pages/webhook_page.py` — webhook config UI | — |
| 4.4 | `ui/pages/trash_page.py` — soft-delete + recovery | — |
| 4.5 | `core/import_export.py` + `ui/dialogs/import_dialog.py` | — |

**Verification:** PiP window appears mid-game. Discord webhook posts clip links. Trash recovers deleted clips. Import external .mp4 works.

### Phase 5: Editing Enhancements (Est. 3-4 sessions)

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 5.1 | `ui/widgets/timeline_editor.py` — split/speed timeline | §6.9 |
| 5.2 | Audio mixer (`ui/widgets/audio_mixer.py`) — per-track volume + mute | §6.9 |
| 5.3 | Filters + overlays + chroma key dialogs | §6.9 |
| 5.4 | Ken Burns effect, crop/rotate | §6.9 |
| 5.5 | `ui/dialogs/merge_dialog.py` + `ui/widgets/transition_picker.py` | §6.9 |
| 5.6 | Music insertion + GIF export | §6.9 |
| 5.7 | AV1 NVENC support (config toggle) | §6.6 (Encoding tab) |

**Verification:** Full editing suite. Timelines, overlays, transitions. AV1 encoding.

### Phase 8: Rename to "Moment" (Est. 1 session)

*Note: Phases 6-7 are intentionally skipped. The original Phase 6 (PiP + Discord + Trash) and Phase 7 (Editor Enhancements) were merged into Phase 4 and Phase 5 respectively when the editing features were moved forward. Phase 8 is the final polish/rename pass.*

| Unit | Deliverable | Spec Ref |
|------|------------|----------|
| 8.1 | Rename package, binary, imports, config paths, DB paths | §2 |
| 8.2 | Rename .desktop file, icon files, all docs | §2 |
| 8.3 | Migration: old clip-tray DB → new Moment DB | §2.3 |
| 8.4 | Backward compat symlink: `clip-tray` → `moment` | §2.3 |

**Verification:** `moment` launches app, reads old DB, shows all clips. `clip-tray` command still works (symlink).

---

## 24. Testing

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | `pytest` | Models, store, config, encoder/uploader command building, corruption detection, retention logic |
| Integration | Manual | Full pipeline (encode → upload), game detection, trim flow |
| UI | Manual | Window behavior, toasts, tray, keyboard shortcuts, visual correctness |
| Migration | `pytest` | Old JSON → SQLite, old clip-tray DB → new Moment DB, edge cases (empty, corrupt, missing) |

---

## 25. Risks

| Risk | Mitigation |
|------|-----------|
| QMediaPlayer Linux support spotty | H264 tested OK. HEVC transcode to H264. PiP uses QPixmap frames (ffmpeg pipe), not QVideoWidget. |
| PiP conflicts with fullscreen GL context | Frame-by-frame QPixmap, not QVideoWidget. Test on Vulkan games. |
| Wayland global hotkeys limited | KDE D-Bus API; XWayland fallback. Document as "best-effort on Wayland" for initial release. |
| Wayland QSystemTrayIcon may not appear | Fall back to StatusNotifierItem. Monitor Qt6/KDE developments. |
| Discord webhook URL leaks | Stored locally only. No server. Revocable via Discord settings. |
| RNNoise quality varies by mic | Bundle cf-librispeech model. Allow per-clip disable. Future: custom model paths. |
| gpu-screen-recorder SIGRTMIN unreliable | Manual bookmark fallback. Test with latest version. |
| GPU contention during encode | Single-thread semaphore. Encode paused during game per game profile. RTX 4080 NVENC is fast (<30s per 5min clip). |
| Migration failure | `clips.json` renamed to `.bak`, never deleted. Full rollback: rename back, delete `clips.db`. |
| Audio routing flags unknown | gpu-screen-recorder audio flags need research during Phase 3 implementation. Documented as TBD in §10.4. |

---

## 26. Remaining Gaps

The following items are acknowledged but not yet fully specified:

| Gap | Section | Impact | Resolution |
|-----|---------|--------|------------|
| **Rclone remote configuration UI** | §9.4 | User must manually configure rclone remote. No UI for setup. | Medium — config step in docs for now. Future: rclone config wizard in Settings. |
| **Keyboard shortcut configuration UI** | §11.5 | Hotkeys are hardcoded F8/F9/F10/Ctrl+F8/Ctrl+F9. No Settings UI for rebinding. | Medium — implement as standalone dialog in Phase 3. |
| **First-run wizard** | — | No onboarding flow for new users with no clips/config. App shows empty state with guide card. | Low — empty state guide card (§6.2) is sufficient for MVP. |
| **Sound notifications** | §6.6 (Notifications tab) | Checkboxes exist but no implementation detail for sound playback (format, files, library). | Low — QSoundEffect with bundled .wav files. Add during Phase 2c. |
| **Trash auto-purge policy** | — | Trashed clips kept indefinitely. No auto-purge. | Low — revisit when trash page is implemented. |
| **Noise suppression implementation** | §3 (Phase 3.5) | RNNoice filter chain, model path, per-clip disable UI not specified. | Low — bundle cf-librispeech model; document as Phase 3 detail pass. |
| **Audio routing flags** | §10.4 | gpu-screen-recorder `--audio` flags per track need research. | Medium — research during Phase 3 implementation. |
| **Screenshot processing** | §3 (Phase 3.4) | Screenshot capture (SIGUSR1) is specified, but post-processing (cropping, naming, thumbnail) is not. | Low — implemented alongside Review Card system in Phase 3.
| **Import/Export detail** | §3 (Phase 4.5) | `core/import_export.py` is in module structure but has no spec beyond "external clip import + batch export". | Low — implement alongside Phase 4 import dialog. |
| **Desktop recording** | §10.4 | `--record-desktop` flag acknowledged but no detail. | Low — fallback mode, not primary. Detail during Phase 3. |
| **YouTube upload** | §14.1 | Mentioned as future permanent archive. No implementation spec. | Low — deferred post-MVP. |
| **Update mechanism** | — | No auto-update. User must `git pull` or `pip install --upgrade`. | Low — out of scope for initial release. |
| **Export batch operation** | §17.2 | User expressed uncertainty about this feature. "Copies encoded MP4s to folder" is proposed. | Low — can be refined or removed during Phase 2b implementation. |

**Note:** All gaps above are **low or medium impact**. They do not block any Phase 0-3 deliverables. Each is tagged with a planned resolution path.

---

## 27. Next Steps

1. Review and approve this consolidated plan
2. Begin Phase 0: Foundation (package scaffold, utils, models, store, migration)
3. Iterate: each phase builds on the previous
4. At Phase 2a completion: cutover from old script (delete `clip-tray.py`)
5. Continue through remaining phases
6. Final Phase 8: rename to "Moment" as polish pass
