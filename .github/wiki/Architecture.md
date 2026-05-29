# Architecture

## Overview

Moment has three layers:

```
┌────────────────────────────────────────────┐
│                UI (PyQt6)                  │
│  Pages │ Dialogs │ Widgets │ Overlay       │
├────────────────────────────────────────────┤
│              Core (pure Python)            │
│  Store │ Encoder │ Uploader │ GSR │ Config │
├────────────────────────────────────────────┤
│        Utils / System (ffmpeg, etc.)       │
└────────────────────────────────────────────┘
```

The core layer must never import from the UI layer — this keeps business logic testable without a display server.

## Startup sequence

```
moment CLI
  │
  ├─► ConfigLoader — reads ~/.config/moment/config.yaml
  ├─► Store — opens ~/.config/moment/clips.db (WAL mode)
  ├─► EncoderDetector — detect_best_encoder()
  ├─► GSRController — start_replay_buffer() with -k flag
  ├─► GSRWatcher — watch output dir for new MKVs
  ├─► GlobalHotkey — register kglobalaccel shortcut
  ├─► TrayIcon — show system tray
  └─► MainWindow — show clip grid (empty state on first run)
```

## Data flow

```
GSR (-k mode)
  │
  │  SIGUSR1 (save replay)
  ▼
MKV file written to ~/Videos/Moment/
  │
  ▼
GSRWatcher (inotify)
  │
  ▼
Store.import_clip(path)
  │
  ├──► file metadata + hash
  ├──► thumbnail generated (320×180)
  ├──► UI notification (grid refresh, toast)
  │
  ▼
Encoder (async via Pipeline)
  │
  ├──► Detect codec → h264_nvenc / vaapi / qsv
  ├──► ffmpeg transcode to compressed MP4
  ├──► Update store: {status: encoded, encoded_path}
  │
  ▼
Uploader (async thread pool, N concurrent)
  │
  ├──► rclone copy to remote:bucket/path
  ├──► Generate shareable URL (if MOMENT_BASE_URL set)
  ├──► Update store: {status: uploaded, remote_url}
  │
  ▼
Toast: "Clip uploaded! Share: https://..."
```

## Threading model

Three thread pools:

| Pool | Threads | GPU | Pauses during gameplay |
|---|---|---|---|
| Encode | 1 | Yes (NVENC semaphore) | Configurable |
| Upload | N (default 2) | No | No |
| Thumbnail | 1 | Yes (shared semaphore) | Configurable |

GPU access is serialized via `threading.BoundedSemaphore(1)` — encode and thumbnail never compete for the hardware encoder simultaneously.

The main Qt thread handles UI only. All disk/GPU I/O happens in worker threads. Results are delivered back to the main thread via `QMetaObject.invokeMethod` or Qt signals.

## Key design decisions

### Why SQLite WAL mode?
- Concurrent reads during encode/upload without blocking
- Database lives at `~/.config/moment/clips.db` (portable, no daemon)
- WAL checkpointing minimizes file size

### Why rclone for uploads?
- 40+ storage providers with one interface
- Battle-tested by thousands of users
- Config is portable (copy `~/.config/rclone/rclone.conf`)
- Encryption, retry, and bandwidth limiting built in

### Why GPU Screen Recorder?
- Best-in-class Linux screen capture with replay buffer
- Uses NVIDIA's SDK directly (NVFBC, NVIFR) for low overhead
- Active development by dec05eba
- Wayland support (via pipewire portal)

### Why kglobalaccel for hotkeys?
- KDE-native global shortcut registration
- Works even when the game has focus
- D-Bus API means we can define shortcuts programmatically
- Falls back to QShortcut for non-KDE desktops

## Database schema

The `clips.db` schema:

```sql
CREATE TABLE clips (
    id TEXT PRIMARY KEY,              -- UUID
    game TEXT NOT NULL,               -- Game name (from window title)
    recorded_at TEXT NOT NULL,        -- ISO 8601 timestamp
    duration_secs REAL NOT NULL,      -- Clip length in seconds
    file_path TEXT NOT NULL,          -- Path to the MKV/MP4 file
    file_size INTEGER NOT NULL,       -- Size in bytes
    file_hash TEXT NOT NULL,          -- SHA-256 of raw clip
    thumbnail_path TEXT,              -- Path to 320×180 PNG
    encoded_path TEXT,                -- Path to transcoded output
    encoded_codec TEXT,               -- Codec used for encoding
    remote_url TEXT,                  -- Shareable URL (after upload)
    status TEXT NOT NULL DEFAULT 'recorded',
        -- recorded → encoding → uploaded | failed
    upload_retries INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE game_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL UNIQUE,
    fps INTEGER DEFAULT 60,
    quality TEXT DEFAULT 'very_high',
    codec TEXT DEFAULT 'auto',
    record_area TEXT DEFAULT 'screen',
    replay_duration INTEGER DEFAULT 60
);

CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

## Overlay

The in-game overlay is a frameless PyQt6 window with:
- `WindowStaysOnTopHint` — always on top
- `FramelessWindowHint` — no chrome
- `WA_TranslucentBackground` — transparent
- `WA_ShowWithoutActivating` — doesn't steal game focus
- `WA_X11NetWmWindowTypeDock` — KWin doesn't focus it

The overlay receives keyboard input only on interactive elements (buttons). Clicking outside them passes the event through to the game.

## Configuration

Config is a YAML file at `~/.config/moment/config.yaml`:

```yaml
db_dir: ~/.config/moment
data_dir: ~/.local/share/moment
gsr_output_dir: ~/Videos/Moment
encoded_dir: ~/.local/share/moment/encoded
thumbnail_dir: ~/.local/share/moment/thumbnails
temp_dir: ~/.local/share/moment/temp
log_dir: ~/.local/share/moment

rclone_remote: r2
rclone_bucket: moment
base_url: ""

recording_mode: replay
gsr_fps: 60
gsr_quality: very_high
gsr_container: mp4
gsr_audio: default_output
gsr_record_area: screen
gsr_show_cursor: true
replay_duration: 60

preferred_codec: auto
encode_pause_during_game: true
max_concurrent_uploads: 2
thumbnail_lru_size: 250

save_clip_hotkey: Ctrl+F12
overlay_hotkey: Alt+Z
```
