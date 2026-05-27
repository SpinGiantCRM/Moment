# Spec: Fleshed-Out Features & Design Decisions

**Date:** 2026-05-27
**Status:** FINAL — decisions confirmed via user interview
**Augments:** `docs/plan.md` — fills in all under-specified sections

---

## 1. Clip Review Cards (New Feature — replaces vague toast concept)

### 1.1 Concept

When a clip is captured (hotkey pressed, gpu-screen-recorder saves replay), a **Clip Review Card** auto-pops up showing a preview of the clip. This is distinct from the toast system — toasts are for notifications (upload complete, errors), review cards are for **instant playback review** of captured moments.

### 1.2 Trigger

- **Auto-popup** immediately after `gpu-screen-recorder` saves a replay
- Displays the **source file** (MKV), not the encoded output
- Encoding happens later (per encode timing settings — see §4)
- Shows last 15 seconds (configurable per game) of the source as a silent mini-player

### 1.3 Visual Design

```
┌──────────────────────────────────────┐
│  ┌──────────────────────────────┐    │
│  │                              │    │  ← Mini video player (no sound)
│  │   LAST 15 SECONDS OF CLIP    │    │     Aspect ratio matches source
│  │                              │    │     4px radius on video area
│  └──────────────────────────────┘    │
│                                      │
│  Counter-Strike 2             2:34   │  ← --text-primary, 12px, 500 weight
│  Just now                      HQ    │  ← --text-secondary, 11px
│                                      │
│  [✏ Rename]  [✂ Trim]  [★ Favorite]  │  ← Action buttons in a floating island
│                                      │
└──────────────────────────────────────┘
```

### 1.4 Dimensions & Positioning

| Size Setting | Card Width | Card Height | Player Height |
|-------------|-----------|-------------|---------------|
| Small | 320px | ~260px | 180px |
| Medium | 420px | ~340px | 236px |
| Large | 520px | ~420px | 292px |

- **Position:** Bottom-right corner of primary monitor
- **Offset from edges:** 24px from right, 24px from bottom (above toasts)
- **Stacking:** If multiple cards are visible, stack with 12px vertical gap between them
- **Max visible:** 3 cards at once. 4th replaces oldest.
- **Z-order:** Above toasts (toasts have lower z-order)

### 1.5 Animation

| Event | Animation | Duration | Easing |
|-------|-----------|----------|--------|
| Appear | Slide in from right | 250ms | `ease-out` |
| Dismiss | Slide out to right + fade | 200ms | `ease-in` |
| New card pushes old up | Smooth translate | 200ms | `ease-out` |
| Hover | Slight lift (2px y-offset + shadow) | 100ms | `ease-out` |

### 1.6 Auto-Dismiss

- **Default duration:** 8 seconds
- **Hover pauses dismiss** — if mouse enters card, auto-dismiss timer is paused
- **Click outside dismisses** all visible cards immediately
- **Close button** (top-right ✕) dismisses individual card
- **Action dismiss** — clicking any action button dismisses after action completes

### 1.7 Actions

| Action | Behavior |
|--------|----------|
| **✏ Rename** | Inline rename field replaces title text. Enter to confirm. Card dismisses after rename. |
| **✂ Trim** | Opens main window to editor view (see §7) with this clip loaded. Card dismisses. |
| **★ Favorite** | Toggle. Card updates instantly, dismisses after 1s with brief 'Favorited ✓' note. |
| **Click video** | Opens main window to player page with this clip. Card dismisses. |
| **✕ Close** | Dismisses card immediately |

### 1.8 Per-Game Configuration (in Game Profile)

Each game profile stores:

```python
@dataclass
class ReviewCardConfig:
    enabled: bool = True          # Show review cards for this game
    size: Literal["small", "medium", "large"] = "medium"
    preview_duration: float = 15.0  # Seconds of preview (5-60)
    
    # What info to show:
    show_game_name: bool = True
    show_duration: bool = True
    show_file_size: bool = True
    show_quality_badge: bool = True
    
    # Action buttons to show:
    show_rename: bool = True
    show_trim: bool = True
    show_favorite: bool = True
    
    # Animation:
    animation_style: Literal["slide", "fade", "scale"] = "slide"
```

### 1.9 Global Defaults (in Settings → General tab)

Same fields as above, with `enabled=True` default. Per-game settings inherit from global defaults and can override.

### 1.10 UI Scaling

The card auto-scales to fit the configured elements. If user disables mini player:
- Card height shrinks to show info section + action buttons only (~80px)
- Width stays the same
- Layout adjusts gracefully — info section becomes a single horizontal row

### 1.11 Edge Cases

| Scenario | Behavior |
|----------|----------|
| Source file deleted before card appears | Card shows "File not found" placeholder, allows rename/delete |
| Multiple rapid captures | Cards stack. Max 3 visible. Oldest dismissed. |
| Game active + card pops up | Card appears over game (frameless, always-on-top). If user is playing, they see it briefly then it auto-dismisses. |
| Screen recording active (OBS, etc.) | Card uses `WA_ShowWithoutActivating` — does NOT steal focus from game/stream |
| Source file is 0 bytes / corrupt | Card shows error state with "Corrupt capture" message |

---

## 2. Clip Encore: Game Exit Flow

### 2.1 Overview

When the game monitor detects `IDLE → GAME_ACTIVE → GAME_EXITING`, and the game session produced new clips:

1. App window opens automatically (if minimized/hidden)
2. Window takes ~60–80% of screen size (not fullscreen, not maximized)
3. Switches to **Editor View** showing the first un-named clip from this session
4. User edits the clip, then names it, then moves to next clip
5. All clips from this session are processed before returning to normal grid

### 2.2 Editor View (Post-Game)

```
┌────────────────────────────────────────────────────────────┐
│  Session: Counter-Strike 2         3 new clips    [×]      │  ← toolbar island
├────────────────────────────────────────────────────────────┤
│                                                             │
│              ┌──────────────────────────────┐              │
│              │                              │              │
│              │     VIDEO PREVIEW            │              │
│              │     (source MKV)             │              │  ← 60% of editor
│              │                              │              │
│              └──────────────────────────────┘              │
│                                                             │
│   ┌─────────[████████████|░ ░ ░ ░ ░ ░]──────────┐         │  ← timeline
│   │  Trim Start          Trim End    0:00/2:34   │         │
│   └──────────────────────────────────────────────┘         │
│                                                             │
│   🔊 Game ──○─────── 100%    🔊 Mic ──○─── 80%              │  ← audio island
│                                                             │
│   ┌─────────────────────────────────────────┐              │
│   │ Clip Name:  [________________________]  │              │
│   │ Game:       [Counter-Strike 2      ▼]  │              │
│   │ Tags:       [clutch] [highlight] [+]   │              │
│   └─────────────────────────────────────────┘              │
│                                                             │
│   [Split] [Speed] [Filters] [Overlays]                     │  ← editing island
│                                                             │
│   [Skip]                    [◀ Prev]  [Next ▶]  [Done]     │
└────────────────────────────────────────────────────────────┘
```

### 2.3 Session Navigation

| Control | Behavior |
|---------|----------|
| **Next ▶** | Save current clip edits, move to next un-named clip from this session |
| **◀ Prev** | Go back to previous clip in session |
| **Done** | Close editor, return to Grid Page. Remaining un-named clips keep auto-generated titles. |
| **Skip** | Discard any edits made to current clip, move to next |
| **× (top-right)** | Same as Done — close editor, return to grid |

### 2.4 Auto-Save

Edits are auto-saved to `EditProfile` in the store when navigating between clips. No explicit "Save" button. The "Done" button merely closes the editor, all edits are already persisted.

### 2.5 When the Editor Opens

| Condition | Behavior |
|-----------|----------|
| Game exits with new clips | Editor opens, window shown & focused |
| Game exits with NO new clips | Nothing happens. App stays hidden. |
| User is actively using the app (window focused) during game exit | A banner appears: "Game ended — 3 new clips ready [Review Now] [Later]" |
| App was open but minimized | Window raised, editor shown |

### 2.6 Edge Cases

| Scenario | Behavior |
|----------|----------|
| User was already editing a clip when game ends | After game exit, a notification asks: "Finish editing current clip or review new session clips?" |
| 15+ clips from one session | Editor loads them. Scroll navigation. Batch renaming option: "Name all: [________]" |
| User closes editor without naming any | Clips retain auto-generated stems as titles. Edits (trim, etc.) still saved. |

---

## 3. Settings Dialog — Full Per-Tab Spec

### 3.1 General Tab

```
┌──────────────────────────────────────────────────┐
│ General                                          │  ← Tab title
├──────────────────────────────────────────────────┤
│                                                   │
│  🔘 Start on login                                │  ← QCheckBox
│     Moment will start minimized to tray when      │     (creates/deletes autostart .desktop)
│     you log in                                     │
│                                                   │
│  🔘 Minimize to tray on close                      │  ← QCheckBox
│     Close button hides the window instead of       │
│     quitting the app                               │
│                                                   │
│  ───────────────────────────────────────────────  │  ← separator
│                                                   │
│  🎬 Default Encode Timing                          │  ← QComboBox
│     [As soon as possible      ▼]                   │
│       • As soon as possible                        │
│       • After game ends                            │
│       • When system is idle                        │
│                                                   │
│  ☐ Also encode during game (bypass pause)          │  ← QCheckBox
│     (Only applies to manual re-encode actions)     │     (disabled if ASAP selected)
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  📁 Storage Locations                              │  ← Section header
│                                                   │
│  Source files:  ~/Videos/Moment/Source/   [Browse] │  ← QLineEdit + button
│  Encoded:       ~/Videos/Moment/Encoded/  [Browse] │
│  Config:        ~/.config/moment/         [Browse] │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  [Reset Database]           [Open Config Folder]   │  ← Action buttons
│                                                   │
└──────────────────────────────────────────────────┘
```

### 3.2 Encoding Tab

```
┌──────────────────────────────────────────────────┐
│ Encoding                                          │  ← Tab title
├──────────────────────────────────────────────────┤
│                                                   │
│  🎥 Video Encoder                                  │  ← Section
│                                                   │
│  Codec:          [H.264 NVENC               ▼]    │  ← QComboBox
│                    • H.264 NVENC (default)          │
│                    • H.265 NVENC                    │
│                    • AV1 NVENC                      │
│                    • Software H.264 (fallback)      │
│                                                   │
│  Preset:          [P7 (Slowest)              ▼]    │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  📊 Bitrate Controls                               │  ← Section
│                                                   │
│  Quality (CQ):    [━━━━━━━━●━━━━━]  23             │  ← QSlider + label
│                   (0=lossless  51=worst)           │
│                                                   │
│  Target bitrate:  [━━━━━●━━━━━━━━━]  12 Mbps       │  ← QSlider + label
│                                                   │
│  Max bitrate:     [━━━━●━━━━━━━━━━]  18 Mbps       │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  🎵 Audio                                           │  ← Section
│                                                   │
│  Audio codec:     [AAC                        ▼]   │
│  Audio bitrate:   [96 kbps                    ▼]   │
│                    • 64 kbps                         │
│                    • 96 kbps (default)               │
│                    • 128 kbps                        │
│                    • 192 kbps                        │
│                    • 320 kbps                        │
│                                                   │
│  ☐ Apply noise suppression to mic track             │  ← QCheckBox
│     (Requires RNNoise — see Noise Suppression)      │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  ⚠ Hardware Acceleration                           │  ← Section
│                                                   │
│  Current GPU: NVIDIA RTX 4080 (NVENC available)    │  ← Read-only status
│  ☐ Fallback to software if NVENC unavailable        │  ← QCheckBox
│                                                   │
└──────────────────────────────────────────────────┘
```

### 3.3 Notifications Tab

```
┌──────────────────────────────────────────────────┐
│ Notifications                                     │  ← Tab title
├──────────────────────────────────────────────────┤
│                                                   │
│  🔔 Toast Notifications                            │  ← Section
│                                                   │
│  ☑ Show upload complete toast                      │  ← QCheckBox
│  ☑ Show encode complete toast (batch only)         │
│  ☑ Show error toasts                               │
│  ☐ Show cleanup toasts                             │
│  ☑ Show low disk space warnings                    │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  🃏 Clip Review Cards                               │  ← Section
│                                                   │
│  ☑ Show review cards after capture                 │  ← QCheckBox (global default)
│  Default size:      [Medium                   ▼]   │  ← QComboBox
│                       • Small                       │
│                       • Medium                      │
│                       • Large                       │
│  Preview duration:  [15                seconds]    │  ← QSpinBox (5-60)
│                                                   │
│  ☑ Show mini video player (can disable per-game)   │  ← QCheckBox
│  ☑ Show game name on card                          │
│  ☑ Show duration on card                           │
│  ☑ Show file size on card                          │
│  ☑ Show quality badge                              │
│  ☑ Show rename button                              │
│  ☑ Show trim button                                │
│  ☑ Show favorite button                            │
│                                                   │
│  Animation style:   [Slide                     ▼]  │  ← QComboBox
│                       • Slide                       │
│                       • Fade                        │
│                       • Scale                       │
│                                                   │
│  ───────────────────────────────────────────────  │
│                                                   │
│  🔈 Sound Notifications                             │  ← Section
│                                                   │
│  ☐ Play sound on capture complete                  │  ← QCheckBox
│  ☐ Play sound on upload complete                   │
│  ☐ Play sound on error                             │
│                                                   │
└──────────────────────────────────────────────────┘
```

### 3.4 Game Detection Tab

```
┌──────────────────────────────────────────────────┐
│ Game Detection                                    │  ← Tab title
├──────────────────────────────────────────────────┤
│                                                   │
│  🎮 Game Process Detection                         │  ← Section
│                                                   │
│  Scan interval:    [3                    sec]      │  ← QSpinBox (1-10)
│                                                   │
│  Known game processes:                             │  ← QListWidget
│  ┌─────────────────────────────────────────┐      │
│  │ cs2                                       │      │
│  │ rocket-league                             │      │
│  │ eldenring.exe                             │      │
│  │ minecraft                                 │      │
│  │ [Add game…]                               │      │
│  └─────────────────────────────────────────┘      │
│                                                    │
│  ☐ Auto-detect new games (scan nvidia-smi)          │  ← QCheckBox
│  ☐ Also detect via KDE fullscreen check             │  ← QCheckBox (Wayland)
│                                                    │
│  ───────────────────────────────────────────────  │
│                                                    │
│  🖥 Behavior During Game                             │  ← Section
│                                                    │
│  During game:                                      │
│  • Encode:          [Paused                   ▼]   │
│  • Upload:          [Running                  ▼]   │
│  • Thumbnail gen:   [Paused                   ▼]   │
│  • Watcher:         [Running                  ▼]   │
│                                                    │
│  ☑ Minimize main window when game starts            │  ← QCheckBox
│  ☐ Show 'Game active' indicator in tray             │  ← QCheckBox
│                                                    │
│  ───────────────────────────────────────────────  │
│                                                    │
│  🚪 On Game Exit                                    │  ← Section
│                                                    │
│  ☑ Open editor for new clips                        │  ← QCheckBox
│  ☐ Auto-tag clips with game name                    │  ← QCheckBox
│  ☑ Minimize to tray after editor closed             │  ← QCheckBox
│                                                    │
│  Default editor window size: 70% of screen          │  ← QSlider 40%-90%
│                                                    │
└──────────────────────────────────────────────────┘
```

### 3.5 Dialog Behavior

- **No Apply button** — Save on tab switch. Change is persisted immediately.
- **Validation** — Inline red border on invalid fields. Tooltip explains valid range.
- **Factory Reset** — Confirmation dialog: "This will reset all settings to defaults. Your clips are not affected. Continue?" — Clears all key-value settings in DB. Does NOT touch clip data.
- **Reset Database** — Separate from Factory Reset. "This will reset the database schema. Clips will be re-migrated from backup. Are you sure?" Danger styling.

---

## 4. Encode Timing Settings

### 4.1 Options

| Setting | Behavior |
|---------|----------|
| **As soon as possible** | Encode starts immediately after thumbnail gen completes (current plan behavior). |
| **After game ends** | Encode tasks are queued but NOT executed while a game is active (GAME_ACTIVE state). They begin when the game monitor transitions to IDLE or GAME_EXITING. |
| **When system is idle** | Encode tasks only execute when the system has been idle for 5+ minutes (no mouse/keyboard input, no active game). Uses `xprintidle` or similar idle detection. Tasks pause if user becomes active. Resume on next idle. |

### 4.2 Per-Game Override

- **Global default** set in Settings → General tab
- **Each game profile** can override the encode timing
- If a game profile has no explicit setting, it inherits the global default
- When no game is detected, "As soon as possible" is always used (regardless of setting)

### 4.3 Implementation

```python
# Stored in settings table and game_profiles table
ENCODE_TIMING_KEY = "encode_timing"  # "asap" | "after_game" | "when_idle"

# In pipeline.py:
# On task queue check:
#   if game_state == GAME_ACTIVE and encode_timing == "after_game":
#       skip encode tasks
#   elif encode_timing == "when_idle" and not system_is_idle():
#       skip encode tasks
#   else:
#       process next encode task
```

---

## 5. Retention Policy

### 5.1 Defaults

| Tier | Retention Rule | Detail |
|------|---------------|--------|
| **Source files** (MKV) | Keep 3 months | Delete source MKVs older than 90 days. Can be overridden per-clip via `protect_from_retention`. |
| **Encoded files** (MP4) | Keep 3 years | Delete encoded MP4s older than 1095 days. |
| **Cloud** (R2) | 8GB rolling limit | Permanent storage until 8GB total. When full, newest replaces oldest (FIFO). Newest is always kept, oldest deleted. |
| **YouTube** | Permanent (future) | When YouTube upload feature is added, clips uploaded there are permanent. Daily upload batch of recent clips. |

### 5.2 Conflict Resolution

When both age and disk-space retention are configured and conflict:
- **Whichever limit would keep fewer clips wins** (most restrictive applies)
- User can change this in retention settings: "When age and disk limits conflict, use the: [more restrictive / less restrictive / disk-space / age] limit"

### 5.3 Protection

- Clips with `protect_from_retention=True` are never deleted by retention rules
- User manually toggles this via clip context menu: "Protect from deletion"
- Protected clips count against disk budgets but are skipped during cleanup

### 5.4 Future: YouTube Archive

- When YouTube upload feature is added, clips become permanent there
- After successful YouTube upload, source and encoded can be deleted by retention
- Daily batch: upload most recent N clips (configurable) to YouTube as unlisted
- YouTube serves as the final permanent archive, replacing the 8GB rolling cloud limit

---

## 6. Stats Dashboard

### 6.1 Layout

```
┌─ margin 16px ─────────────────────────────────────────────────────┐
│ Dashboard                                                    [↻]  │  ← Page title + refresh
├──────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │   Total   │ │  Storage  │ │ Uploads  │ │   This   │            │  ← Metric cards
│  │   Clips   │ │   Used   │ │   Today  │ │   Week   │            │     (4 across)
│  │   1,234   │ │  45.2 GB │ │    12    │ │    47    │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
│                                                                     │
│  ┌─────────────────────────────────────┐                          │
│  │                                     │                            │
│  │   Storage by Game (donut chart)     │                            │  ← Left: storage distribution
│  │   🟦 CS2              22.4 GB      │                            │
│  │   🟩 Rocket League     8.1 GB      │                            │
│  │   🟧 Minecraft         5.3 GB      │                            │
│  │   🟨 Elden Ring         3.2 GB      │                            │
│  │   ⬜ Other             6.2 GB      │                            │
│  └─────────────────────────────────────┘                          │
│                                                                     │
│  ┌─────────────────────────────────────┐                          │
│  │                                     │                            │
│  │   Captures Over Time (bar chart)    │                            │  ← Right: daily captures
│  │   ██ ████ █ ██████ ███ ████████    │                            │     (last 30 days)
│  │   Mon Tue Wed Thu Fri Sat Sun       │                            │
│  └─────────────────────────────────────┘                          │
│                                                                     │
│  ┌────────────────────────────────────────────────────────┐       │
│  │  Recent Uploads                                         │       │  ← List: last 10 uploads
│  │  ┌──────────────────────────────────────────────┐      │       │
│  │  │ CS2 clutch ace_2026-05-27.mp4    2 min ago  ✓ │      │       │
│  │  │ RL save of the game_2026-05-27.mp4  5 min ago ✓ │      │       │
│  │  └──────────────────────────────────────────────┘      │       │
│  └────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │  Encode  │ │   Top    │ │  Total   │ │  Avg     │            │  ← Bottom metric row
│  │  Speed ⚡ │ │   Game   │ │  Upload  │ │  Clip    │            │
│  │  12.3x   │ │   CS2    │ │  8.4 GB  │ │  2:34    │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
│                                                                     │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 Metrics Detail

| Metric | Source | Update Frequency |
|--------|--------|-----------------|
| Total clips | `SELECT COUNT(*) FROM clips WHERE deleted_at IS NULL` | On new clip, on delete |
| Storage used | Sum of file sizes for source + encoded on disk | Every 120s (health check) |
| Uploads today | `SELECT COUNT(*) FROM clips WHERE uploaded_at > today()` | On upload |
| This week | `SELECT COUNT(*) FROM clips WHERE recorded_at > 7 days ago` | On app start + every 120s |
| Storage by game | `SELECT game, SUM(file_size) GROUP BY game` | Every 120s |
| Captures over time | `SELECT DATE(recorded_at), COUNT(*) GROUP BY DATE` last 30 days | On app start + every 120s |
| Recent uploads | `SELECT title, uploaded_at FROM clips WHERE uploaded ORDER BY uploaded_at DESC LIMIT 10` | On app start, on upload |
| Encode speed | Average encode speed ratio from last 10 encodes (logged in pipeline) | After each encode |
| Most captured game | `SELECT game, COUNT(*) GROUP BY game ORDER BY COUNT DESC LIMIT 1` | On app start |
| Total uploaded | `SELECT SUM(file_size) FROM clips WHERE status=UPLOADED` | On app start + on upload |
| Average duration | `SELECT AVG(duration) FROM clips WHERE deleted_at IS NULL` | On app start |

### 6.3 Chart Implementation

- **Donut chart:** Custom QWidget with QPainter. `drawPie()` for segments. Single large arc for each game.
- **Bar chart:** Custom QWidget with QPainter. 30 bars for 30 days. `QPainter.drawRect()`.
- **No external charting library** — keep dependencies minimal. All charts are custom QPainter widgets.
- Colors come from game palette (auto-generated from game name hash, or custom colors from game profiles).

---

## 7. Editor View (Full Phase 7 Features)

### 7.1 Immediate Availability

The full editing suite is available from day one in the post-game editor view. Not just trim — every feature from Phase 7.

### 7.2 Editor Sections

| Section | Widget | Features |
|---------|--------|----------|
| **Video Preview** | `QVideoWidget` | Source MKV playback. 60% of editor height. |
| **Timeline** | Custom `TimelineEditor` | Trim handles, split points, speed ramp curves |
| **Audio Mix** | `AudioMixer` | Game audio slider, mic audio slider, mute per track |
| **Metadata** | Inline form | Title, game selector, tags (with autocomplete) |
| **Effects** | Button row → panels | Filters (brightness, contrast, saturation), Overlays (text, image), Chroma key |

### 7.3 Feature Breakdown (from Phase 7, now immediate)

| Feature | Implementation |
|---------|---------------|
| **Trim** | Custom dual-handle timeline (§5.4 of plan) |
| **Split** | Button or hotkey (S) at playhead position. Creates new segment in timeline. |
| **Speed** | Per-segment speed multiplier (0.1x to 4x). Dropdown or slider when segment selected. |
| **Audio mix** | Two sliders: game audio 0-200%, mic audio 0-200%. Independent mute toggles. |
| **Filters** | Brightness (-100 to +100), Contrast (-100 to +100), Saturation (0 to 200), Hue rotation. |
| **Overlays** | Text overlay (font, size, position, duration). Image overlay (PNG, position, scale, duration). |
| **Chroma key** | Color picker for key color, tolerance slider, smoothness slider. Preview checkbox. |
| **Merge** | Add clips to merge list. Reorder. Crossfade/whip transition between segments (in `TransitionPicker`). |
| **Ken Burns** | "Auto-zoom" toggle per clip segment. Start scale + end scale. Start position + end position. |
| **Crop/Rotate** | Crop rectangle overlay on preview. Rotation 0/90/180/270. |
| **Music** | Add background audio file. Volume slider. Fade in/out duration. |
| **GIF** | Export selected segment as GIF. Resolution slider (320p-1080p). Frame rate selector. |

### 7.4 Editor State Persistence

Edits are saved to `EditProfile` in the store as the user makes changes (auto-save on navigation, on pause > 2 seconds, on close). No "Save" button.

---

## 8. Batch Operations

### 8.1 Selection Model

- **Checkbox mode** in grid page (toggle via toolbar button or Ctrl+A)
- Each card has a checkbox in top-left when in selection mode
- Selected count shown in toolbar: "3 selected"
- Enter/Exit selection mode via toolbar button or Esc to exit

### 8.2 Operations

| Operation | Behavior |
|-----------|----------|
| **Delete** | Trash selected clips (soft-delete). If already in trash, permanently delete. |
| **Add tag** | Dialog: "Add tag to N clips" — text input + existing tags. Tag added to all selected. |
| **Remove tag** | Dialog: "Remove tag from N clips" — list of common tags. Selected tag removed from all. |
| **Toggle favorite** | ★/☆ all selected clips (toggle — if all are favorite, unfavorite; if mixed, favorite all) |
| **Re-encode** | Re-encode selected clips with current quality settings. Queues in pipeline. |
| **Re-upload** | Re-upload selected clips to R2 (delete old, upload new). |
| **Move to folder** | Dialog: select or create folder. All selected clips moved. |
| **Set game** | Dialog: "Set game for N clips" — text input with autocomplete of known games. Game set on all. |
| **Export** | Dialog: "Export N clips" — target folder, copy or re-encode. Copies encoded MP4s to chosen folder. |

### 8.3 Multi-Select Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+A | Select all visible clips |
| Shift+click | Range select (select from last clicked to clicked) |
| Ctrl+click | Toggle individual selection |
| Esc | Exit selection mode |

---

## 9. Empty States

### 9.1 Grid Page (No Clips)

```
┌─────────────────────────────────────────────────────┐
│                                                       │
│                                                       │
│              ┌──────────────────────────┐            │
│              │                          │            │
│              │     📹  No Clips Yet     │            │
│              │                          │            │
│              │  Capture your first clip │            │
│              │  by pressing F8 while    │            │
│              │  playing a game.         │            │
│              │                          │            │
│              │  [View Keyboard Shortcuts]            │
│              │  [Open Capture Settings]              │
│              │                          │            │
│              └──────────────────────────┘            │
│                                                       │
│                                                       │
└─────────────────────────────────────────────────────┘
```

- Centered card, 400px wide
- `--bg-surface` background, 8px radius
- Icon is a large (48px) centered camera/clapperboard SVG
- "No Clips Yet" in 15px 600 weight `--text-primary`
- Body text in 12px 400 weight `--text-secondary`
- Two action buttons in a floating island below the text

### 9.2 Trash Page (Empty Trash)

```
┌─────────────────────────────────────────────────────┐
│               🗑 Trash is empty                       │
│                                                       │
│  Deleted clips will appear here. They are             │
│  automatically removed after 30 days.                 │
└─────────────────────────────────────────────────────┐
```

- Simplified version. Single centered text block.
- Icon + two-line text. No action buttons.

### 9.3 Player Page (No Clip Selected)

```
┌─────────────────────────────────────────────────────┐
│                                                       │
│              🎬 Select a clip to play                 │
│                                                       │
│  Click on a clip from the grid or use the              │
│  right-click menu to open in the player.               │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### 9.4 Webhook Page (No Webhooks)

```
┌─────────────────────────────────────────────────────┐
│               🔗 No webhooks configured               │
│                                                       │
│  Add a Discord webhook URL to automatically post       │
│  clip uploads to your Discord server.                  │
│                                                       │
│  [Add Webhook]                                         │
└─────────────────────────────────────────────────────┘
```

---

## 10. Loading / Progress States

### 10.1 Skeleton Loading Animation (Grid Page)

When the app first starts and clips are loading from the store, show skeleton card placeholders:

```
┌──────────────────────┐
│  ┌──────────────────┐│
│  │ ░░░░░░░░░░░░░░░░ ││  ← Skeleton rect (thumbnail area)
│  │ ░░░░░░░░░░░░░░░░ ││     240×135, 4px radius
│  └──────────────────┘│  ← --bg-elevated fill
│  ░░░░░░░░░░░░░       │  ← 80px wide skeleton line (title)
│  ░░░░░░░             │  ← 50px wide skeleton line (metadata)
└──────────────────────┘
```

**Animation:** Pulse effect — opacity oscillates between 0.4 and 0.8 over 1.5s cycle. CSS `@keyframes pulse` or QPropertyAnimation on opacity of a placeholder widget.

**Number of skeletons:** Show 8 skeleton cards (2 rows of 4) during loading. Hidden when data arrives.

### 10.2 Progress Ring (Clip Cards During Encode)

**When visible:** On clip cards in grid where `status == PENDING or ENCODING`.
**Size:** 48px diameter, centered on the thumbnail area.
**Stroke:** 3px, `--accent-blue` for active, `--accent-orange` for queued.
**Background arc:** Thin (1px) `--bg-elevated` full circle behind the progress arc.

**Animation:**
- **Queued (PENDING):** Static arc showing 100% of the ring (full circle), indicating "waiting"
- **Encoding (ENCODING):** Animated arc that sweeps 0→360° continuously (30fps via QTimer 33ms). Does NOT show actual progress (ffmpeg progress parsing is unreliable). Instead, shows a spinning indeterminate arc.
- **Done (DONE):** Arc snaps to full circle green (1s), then fades out over 500ms and ring disappears.

**Implementation:**
```python
class ProgressRing(QWidget):
    def __init__(self):
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(33)  # ~30fps

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Draw background arc
        # Draw foreground arc sweeping 0→360°
```

### 10.3 Processing Banner

Shown at top of grid page when pipeline is active:

```
[Encoding 2/5 · Uploading 1/3  ████████░░░░░░░]  
```

- Single line, 28px height, `--bg-surface` background
- Left side: text summary of pipeline state
- Right side: progress bar (indeterminate if no progress info, determinate if available)
- Updated every 3 seconds (from §7.3 of plan)
- Dismissible via × button (hides until next pipeline change)

---

## 11. Logging

### 11.1 Strategy

Both file and systemd journal:

| Destination | Path | Level | Format |
|-------------|------|-------|--------|
| **File** | `~/.local/share/moment/moment.log` | INFO (DEBUG with `--verbose`) | `[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message` |
| **Systemd journal** | via `systemd.journal` or print to stderr | Same as file | Structured (journald parses stderr) |

### 11.2 Rotation

- Auto-rotate at 10MB (delete old, keep current)
- Keep 7 days of history (7 `.log.1`, `.log.2` files)
- Log rotation handled in-app (check file size on each write)

### 11.3 Log Levels

| Level | Used for |
|-------|----------|
| ERROR | Pipeline failures, DB errors, unexpected exceptions |
| WARNING | Non-critical: retry attempts, missing deps, config fallbacks |
| INFO | Pipeline state transitions, encode start/end, upload start/end, game state changes |
| DEBUG | FFmpeg command strings, subprocess output, signal emissions, timer ticks |

### 11.4 --verbose Flag

- Enables DEBUG level logging to both file and stderr
- Useful for debugging pipeline issues
- NO performance impact in normal operation (INFO-level logs are infrequent)

---

## 12. Recorder Controller — Implementation Pattern

### 12.1 Subprocess Management

```python
class RecorderController:
    """Manages gpu-screen-recorder as a subprocess."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._current_profile: GameProfile | None = None

    def start_recording(self, profile: GameProfile) -> None:
        """Kill existing process if any, spawn new gpu-screen-recorder with profile params."""
        self.stop_recording()
        cmd = self._build_command(profile)
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Process group for signal sending
        )

    def stop_recording(self) -> None:
        """Send SIGTERM to gpu-screen-recorder process."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)

    def save_replay(self, seconds: int = 30) -> None:
        """Send SIGRTMIN to save replay buffer."""
        if self._process and self._process.poll() is None:
            # SIGRTMIN typically saves a replay
            self._process.send_signal(signal.SIGRTMIN)
            # Also write Bookmark to DB

    def take_screenshot(self) -> None:
        """Send SIGUSR1 to capture screenshot."""
        if self._process and self._process.poll() is None:
            self._process.send_signal(signal.SIGUSR1)
```

### 12.2 SIGRTMIN Signal Mapping

| Action | Signal | 
|--------|--------|
| Save 30s replay | `SIGRTMIN` |
| Save 60s replay | `SIGRTMIN + 1` |
| Save 5min replay | `SIGRTMIN + 2` |
| Take screenshot | `SIGUSR1` |

In Python: `signal.SIGRTMIN` → `signal.SIGRTMIN + n` where `n` is the real-time signal offset defined by gpu-screen-recorder.

### 12.3 Profile Switching

When game monitor detects `IDLE → GAME_ACTIVE`:
1. Look up game in `game_profiles` table
2. If profile exists with custom params → stop current recording → start with new params
3. If no profile → continue with default/current params

---

## 13. Hotkey Daemon — Implementation Patterns

### 13.1 Backend Selection

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

### 13.2 SIGRTMIN Backend (Primary)

- gpu-screen-recorder must be running (managed by `RecorderController`)
- Send signals to the recorder subprocess (not to self)
- No external library needed — `subprocess.send_signal()`

### 13.3 KDE D-Bus Backend

```python
# Register global shortcuts via KDE D-Bus API
import dbus

bus = dbus.SessionBus()
kglobal = bus.get_object('org.kde.kglobalaccel', '/kglobalaccel')
kglobal_interface = dbus.Interface(kglobal, 'org.kde.KGlobalAccel')

# Register shortcut
action = kglobal_interface.registerShortcut(
    "Moment Save Replay",           # component friendly name
    "Save Replay",                   # friendly name
    "F8",                            # shortcut string
    "Moment",                        # component unique name
    True                             # unique global shortcut
)

# Listen for activated signal
bus.add_signal_receiver(
    self._on_hotkey_activated,
    signal_name="shortcutActivated",
    dbus_interface="org.kde.kglobalaccel",
    path="/kglobalaccel"
)
```

### 13.4 X11 Backend (Fallback)

```python
# Using python-xlib
from Xlib import X, XK
from Xlib.ext import record
from Xlib.protocol import rq

# Record extension context
ctx = record.RecordContext(display)
ctx.enable_context(True)

# In event loop:
# Listen for KeyPress events
# Match against configured keycodes
# Trigger appropriate action
```

### 13.5 Registered Hotkeys

| Hotkey | Action | Added By |
|--------|--------|----------|
| F8 | Save 30s replay | Default |
| F9 | Save 60s replay | Default |
| F10 | Save 5min replay | Default |
| Ctrl+F8 | Take screenshot | Default |
| Ctrl+F9 | Bookmark current position | Default |
| *User configurable* | *Any action above* | Settings → Keyboard |

---

## 14. Corruption Detection & Health Checks

### 14.1 Health Checks (Every 120s)

| Check | Method | Action on Failure |
|-------|--------|-------------------|
| **Disk space** | `shutil.disk_usage()` on home partition | If <5GB free: warning toast. If <1GB: warning toast + disable encoding |
| **Temp file age** | Scan `/tmp/*.h264.mp4`, check mtime > 1 hour | Delete stale temp files. Log count. |
| **DB integrity** | `PRAGMA integrity_check` on SQLite | If fails: error toast, show "Reset Database" button |
| **Pipeline stuck check** | Check if any task has been `PENDING` or `ENCODING` for >30 minutes | Mark as ERROR. Notify user. |

### 14.2 Corrupt Detection (Per-Clip)

When a clip is first discovered by the watcher:

| Check | Method | Result |
|-------|--------|--------|
| **Zero-byte file** | `os.path.getsize()` == 0 | Mark as CORRUPT immediately |
| **ffprobe probe** | Run ffprobe, parse output | If no video stream → CORRUPT. If duration is 0 → CORRUPT. |
| **Partial write** | mtime < 30 seconds ago + file size growing | Skip for this scan cycle. Wait for stable file. |
| **Container corrupt** | ffmpeg returns error when trying to decode first frame | Mark as CORRUPT |

Clip status `CORRUPT` shows a red badge on the card. User can:
- **Retry** — re-run ffprobe check
- **Delete** — remove from store and disk
- **Ignore** — keep as-is (file may be playable despite probe failure)

### 14.3 Temp Cleanup

- Scan `/tmp/clip-tray-*.mp4` every 120s (during health check)
- Delete files with mtime > 1 hour (orphaned from crashed encodes)
- Log: "Temp cleanup: removed N orphaned files (freed X MB)"

---

## 15. Bookmark Integration

### 15.1 How Bookmarks are Created

- By hotkey (Ctrl+F9 default) → `Bookmark` record written to DB + SIGRTMIN signal
- Bookmark stores: `session_stem`, `offset_seconds`, `label`
- Label can be added via dialog that appears when bookmark is created (optional)

### 15.2 How Bookmarks Become Trim Points

In the editor, when viewing a clip that has associated bookmarks:
- Bookmarks appear as diamond markers on the timeline
- Right-click bookmark → "Set trim start here" / "Set trim end here"
- User can also click the bookmark to jump playhead to that position

---

## 16. Per-Game Profiles — Full Config

Each game profile stores:

```python
@dataclass
class GameProfile:
    id: str                           # UUID
    game_name: str                     # Binary name (e.g., "cs2")
    display_name: str                  # "Counter-Strike 2"
    
    # Recording
    replay_duration: int = 30          # Default F8 duration (seconds)
    audio_config: dict = None          # gpu-screen-recorder audio flags
    capture_fps: int = 60              # Capture frame rate
    
    # Encoding (override global)
    encode_timing: str | None = None   # None = inherit global default
    quality_preset: str | None = None  # Override CQ value
    
    # Pipeline overrides
    pause_encode: bool = True          # Pause encode during this game
    pause_thumbnail: bool = True       # Pause thumbnail gen during this game
    
    # Post-game
    auto_tag: bool = True              # Auto-tag clips with game name
    auto_open_editor: bool = True      # Open editor on game exit
    
    # Review Cards
    review_card: ReviewCardConfig = field(default_factory=ReviewCardConfig)
```

---

## 17. Game Profiles Dialog

```
┌──────────────────────────────────────────────────────┐
│  Game Profiles                                [×]    │
├──────────────────────────────────────────────────────┤
│                                                        │
│  ┌──────────────────────────────────────────────┐    │
│  │ cs2                    🔴 Recording    [Edit] │    │  ← List of known games
│  │ rocket-league          🟢 Not active   [Edit] │    │
│  │ minecraft              🟢 Not active   [Edit] │    │
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
│  ☑ Show file size                                       │
│                                                        │
│  [Delete Profile]              [Cancel]  [Save]        │
└────────────────────────────────────────────────────────┘
```

---

## 18. Phase Allocation Updates

### 18.1 New Chunks

Add to Phase 2 (GUI Skeleton):

| Unit | Deliverable | Spec Reference |
|------|------------|---------------|
| 2.12 | `core/game_profiles.py` + `ui/dialogs/game_profile_dialog.py` — per-game config | §16, §17 |
| 2.13 | Clip Review Cards (`ui/widgets/review_card.py`) | §1 |
| 2.14 | Game exit flow — app opens to editor view | §2 |
| 2.15 | Encode timing settings (global + per-game) | §4 |
| 2.16 | Retention manager (`core/retention.py` full spec) | §5 |
| 2.17 | Stats Dashboard (`ui/pages/stats_page.py` full spec) | §6 |
| 2.18 | Editor view (post-game editor with full Phase 7 features) | §7 |
| 2.19 | Batch operations in grid page | §8 |
| 2.20 | Empty states for all pages | §9 |
| 2.21 | Skeleton loading + progress ring widgets | §10 |
| 2.22 | Logging module (`utils/logging.py`) | §11 |
| 2.23 | Recorder controller full implementation | §12 |
| 2.24 | Hotkey daemon implementation (all backends) | §13 |
| 2.25 | Corruption detection + health checks | §14 |

### 18.2 Removed

| Item | Reason |
|------|--------|
| "Process now" override (§8.2) | Replaced by encode timing settings (§4) |
| Prompt for unclipped clips (§3.4) | Replaced by app-open-on-game-exit flow (§2) |

### 18.3 Phase 7 Merged into Phase 2

The editor features originally planned for Phase 7 (trim, split, speed, audio mix, filters, overlays, chroma key, Ken Burns, crop/rotate, music, GIF) are now part of the immediate editor experience in Phase 2/3.

---

## 19. Verification / Acceptance Criteria

1. Settings dialog has all 4 tabs with all fields specified above
2. Clip Review Card appears after capture, shows 15s silent preview, configurable per game
3. App opens automatically when game exits, showing editor view at 70% screen size
4. Editor has: video preview, trim handles, split, speed, audio mix, filters, overlays, chroma key
5. Encode timing setting (per-game) controls when encoding starts
6. Retention: source 3mo, encoded 3yr, cloud 8GB rolling
7. Dashboard shows: total clips, storage by game donut, 30-day bar chart, recent uploads
8. Batch select: delete, tag, favorite, re-encode, re-upload, move folder, set game, export
9. Empty states: grid page shows launch guide card
10. Skeleton cards pulse during loading, progress ring spins during encode
11. Logging writes to both `~/.local/share/moment/moment.log` and stderr for journald
12. Recorder controller starts/stops gpu-screen-recorder per game profile
13. Hotkey daemon registers F8/F9/F10/Ctrl+F8/Ctrl+F9
14. Health checks run every 120s, detect corrupt files, clean temp files
