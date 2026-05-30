# Moment Architecture

GPU-accelerated game clip manager for Linux. This document describes the system architecture at multiple levels of abstraction.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface (PyQt6)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │  Grid    │  │  Player  │  │  Stats   │  │  Recording     │  │
│  │  Page    │  │  Page    │  │  Page    │  │  Page          │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       │              │             │                │           │
│  ┌────┴──────────────┴─────────────┴────────────────┴────────┐  │
│  │                    MainWindow (QStackedWidget)             │  │
│  └────────────────────────────┬───────────────────────────────┘  │
│                               │                                  │
│  ┌────────────────────────────┴───────────────────────────────┐  │
│  │                    AppManager (QObject)                     │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │  │
│  │  │  Tray    │ │  Overlay │ │ Hotkey   │ │  Clipboard   │  │  │
│  │  │  Icon    │ │  Widget  │ │ Manager  │ │  Manager     │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │  │
│  └────────────────────────────┬───────────────────────────────┘  │
└───────────────────────────────┼───────────────────────────────────┘
                                │ Signals / direct calls
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Business Logic                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Pipeline                                │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │  Encode  │  │  Upload  │  │Thumbnail │  │  Status  │  │   │
│  │  │  Worker  │  │  Worker  │  │  Worker  │  │ Reporter │  │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────┘  │   │
│  │       │              │             │                       │   │
│  │  ┌────┴──────────────┴─────────────┴──────────────────┐   │   │
│  │  │              Priority Task Queue                    │   │   │
│  │  └────────────────────────┬───────────────────────────┘   │   │
│  └───────────────────────────┼──────────────────────────────┘   │
│                               │                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  Store   │  │  Config  │  │  Models  │  │  Utils   │        │
│  │ (SQLite) │  │  (K/V)   │  │ (Datas)  │  │(ffmpeg)  │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│       │              │             │              │              │
│  ┌────┴──────────────┴─────────────┴──────────────┴────────┐   │
│  │              External Integrations                        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │  GSR     │ │  ffmpeg  │ │  rclone  │ │ Discord  │    │   │
│  │  │ Controller│ │  NVENC   │ │  Upload  │ │  Bot     │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Request Flow: Capture to Cloud URL

```
User presses hotkey (Alt+Z)            User plays a game
  │                                      │
  ▼                                      ▼
Overlay appears                       GSRController records to VRAM
  │                                      │
  ├─ F8 → Save 30s replay               │  (circular replay buffer)
  ├─ F9 → Save 60s replay               │
  └─ Open Moment UI                     │
                                         │
                User action or game exit triggers save
                                         │
                                         ▼
                              GSR writes MKV to disk
                                         │
                                    ── Filesystem ──
                                         │
                                    GSRWatcher detects new file
                                         │
                                         ▼
                              Pipeline.enqueue(ENCODE)
                                         │
                              ┌───────────┼───────────┐
                              │           │           │
                              ▼           ▼           ▼
                        ffprobe     Thumbnail    Store.update(
                        metadata    generate     status=ENCODING)
                              │           │
                              └─────┬─────┘
                                    │
                                    ▼
                        Encoder.encode(clip, edit_profile)
                              │
                              ▼
                        ffmpeg NVENC → encoded.mp4
                              │
                              ▼
                        Store.update(status=DONE)
                              │
                              ▼
                        Pipeline.enqueue(UPLOAD)
                              │
                              ▼
                        Uploader.upload(encoded.mp4)
                              │
                              ▼
                        rclone copy → Cloud (R2/S3/B2/...)
                              │
                              ▼
                        Store.update(status=UPLOADED, r2_url=...)
                              │
                              ▼
                        GUI signals → Toast + Grid refresh
                              │
                    ┌─────────┴────────────┐
                    │                      │
                    ▼                      ▼
              Discord webhook         MCP notification
              (if configured)         (if connected)
```

---

## 3. Request Flow: Clip Playback

```
User clicks clip in Grid Page
  │
  ▼
MainWindow.show_player(clip_id)
  │
  ▼
PlayerPage.load_clip(clip_id)
  │
  ├─ Store.get_clip(clip_id)
  ├─ Check for encoded_path (prefer encoded)
  ├─ Fallback to source_path
  └─ Check for edit_profile (apply trim if present)
  │
  ▼
QMediaPlayer loads and plays video
  │
  ├─ Metadata display (duration, game, tags, resolution)
  ├─ Action buttons (favorite, share, delete, edit)
  └─ URL copy with 60s clipboard auto-clear
```

---

## 4. Database Schema

**File:** `src/moment/core/store.py` (schema in `_SCHEMA_SQL`)

**Tables (15 total):**

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `clips` | Primary clip storage | id, stem, source_path, status, game, visibility, discord_user_id |
| `tags` | Tag definitions | id, name, color |
| `clip_tags` | M:N clip↔tag mapping | clip_id, tag_id |
| `edit_profiles` | Per-clip editing profile | clip_id, trim_start, trim_end, segments, filters, overlays |
| `bookmarks` | Session bookmark markers | id, session_stem, offset_seconds, label |
| `webhooks` | Discord webhook config | id, url (encrypted), name, enabled, notify_on, include_clip_url |
| `webhook_log` | Webhook delivery history | id, webhook_id, clip_id, success, status_code |
| `folders` | Clip folders | id, name |
| `folder_clips` | M:N folder↔clip mapping | folder_id, clip_id |
| `game_profiles` | Per-game recording settings | id, game_name, replay_duration, capture_fps, post_capture_action |
| `tasks` | Pipeline task persistence | id, type, priority, payload, status, retry_count |
| `url_history` | URL copy audit trail | id, clip_id, url, copied_at |
| `rate_limits` | Persistent rate limiting | key, last_called, expires_at |
| `pip_cache` | PIP window cache | id, clip_id, start_offset, end_offset |
| `settings` | Config key-value store | key, value |

**Migration pattern:** Each migration method (`_migrate_*`) checks column existence via `PRAGMA table_info` before applying `ALTER TABLE`. All columns also exist in the `CREATE TABLE IF NOT EXISTS` statement for fresh installs.

---

## 5. Encryption Architecture

```
┌────────────────────────────────────────────────────────────┐
│                   OS Keyring (keyring)                      │
│  ┌────────────────────┐  ┌──────────────────────────────┐  │
│  │ db_encryption_key  │  │ webhook_encryption_key       │  │
│  │ (hex, 256-bit)     │  │ (base64 Fernet key)          │  │
│  └────────┬───────────┘  └──────────────┬───────────────┘  │
│           │                              │                  │
│  ┌────────┴───────────┐  ┌──────────────┴───────────────┐  │
│  │ discord_bot_token  │  │ ... (future secrets)         │  │
│  └────────────────────┘  └──────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌─────────────────────┐    ┌──────────────────────────────┐
│ SQLCipher (AES-256) │    │ Fernet (AES-128-CBC + HMAC) │
│ Entire DB encrypted │    │ Webhook URLs encrypted      │
│ at rest             │    │ individually                │
└─────────────────────┘    └──────────────────────────────┘
```

---

## 6. Thread Model

```
Main Thread (Qt Event Loop)
├── QApplication event processing
├── Signal/Slot dispatch
├── UI rendering
└── Toast notifications

Pipeline Threads (daemon=True)
├── Encode Worker (1)       ← GPU-bound, pauses during game
├── Upload Worker (2)       ← IO-bound, runs during game
└── Thumbnail Worker (1)    ← GPU-bound, pauses during game

GSR Controller Thread
└── GSR subprocess management

Game Monitor Thread
└── Process polling for game detection

GSR Watcher Thread
└── Inotify-based filesystem monitoring
```

**Thread safety rules:**
- UI updates via `pyqtSignal` only (never direct calls from workers)
- Store uses `threading.Lock` for write transactions
- Pipeline pausing uses `threading.Condition`
- Active task counters use `threading.Lock`

---

## 7. Key Dependencies

| Dependency | Purpose | Required? |
|------------|---------|-----------|
| PyQt6 | GUI framework | Yes |
| cryptography | Fernet encryption for webhook URLs | Yes |
| pysqlcipher3 | SQLite encryption at rest | Yes |
| keyring | OS keyring integration | Yes |
| ffmpeg/ffprobe | Video encoding, probing, thumbnail | Yes |
| rclone | Cloud storage upload | Yes |
| gpu-screen-recorder | Screen capture | No (optional) |
| discord.py | Discord bot | No (optional: `[bot]`) |
| fastmcp | MCP server | No (optional: `[mcp]`) |
| python-magic | MIME type detection | No (optional: `[import-export]`) |

---

## 8. Game Profiles & Auto-Detection

```
GameMonitor (process polling)
  │
  ├─ Game process detected → emit GAME_ACTIVE
  │   ├─ Pipeline.pause() — GPU tasks suspended
  │   ├─ Lookup GameProfile by game name
  │   │   ├─ Apply custom replay_duration
  │   │   ├─ Apply custom encode_timing
  │   │   ├─ Apply custom quality_preset
  │   │   └─ Apply auto_tag
  │   └─ Optional: minimize UI during game
  │
  └─ Game process exits → emit IDLE
      ├─ Pipeline.resume() — GPU tasks continue
      └─ Post-capture action (review card / discard / editor)
```

---

## 9. Pipeline Task Flow

```
                        ┌──────────────┐
                        │  Task Queue  │
                        │ (PriorityQueue)│
                        └──────┬───────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
            ┌───────▼───────┐    ┌───────▼───────┐
            │  ENCODE task  │    │ UPLOAD task   │
            │  priority=10  │    │  priority=1   │
            └───────┬───────┘    └───────┬───────┘
                    │                     │
            ┌───────▼───────┐    ┌───────▼───────┐
            │ 1. Probe meta │    │ 1. Read file  │
            │ 2. Apply edits │    │ 2. rclone copy │
            │ 3. ffmpeg enc  │    │ 3. Store URL  │
            │ 4. Update clip │    │ 4. Notify GUI │
            │ 5. Enqueue upl │    │               │
            └───────────────┘    └───────────────┘
                    │
            ┌───────▼───────┐
            │ THUMBNAIL     │
            │ task          │
            │ priority=5    │
            └───────┬───────┘
                    │
            ┌───────▼───────┐
            │ 1. ffmpeg seek│
            │ 2. Frame save │
            │ 3. Store path │
            └───────────────┘
```

---

## 10. Module Dependency Graph

```
moment.main
├── moment.ui.app          → AppManager, QApplication
│   ├── moment.ui.main_window → MainWindow, pages
│   │   ├── moment.ui.pages.*
│   │   ├── moment.ui.dialogs.*
│   │   └── moment.ui.widgets.*
│   ├── moment.ui.tray     → TrayIcon
│   ├── moment.ui.resources → stylesheet, icons
│   └── moment.ui.services.*
├── moment.core.*
│   ├── moment.core.store  → SQLite persistence
│   ├── moment.core.config → Key-value settings
│   ├── moment.core.models → Dataclasses & enums
│   ├── moment.core.pipeline → Task queue & workers
│   ├── moment.core.encoder → ffmpeg NVENC
│   ├── moment.core.uploader → rclone upload
│   ├── moment.core.thumbnail → Thumbnail gen
│   ├── moment.core.gsr_controller → GSR subprocess
│   ├── moment.core.gsr_watcher → GSR file monitor
│   ├── moment.core.game_monitor → Process polling
│   └── moment.core.* → Other core modules
├── moment.utils.*
│   ├── moment.utils.ffmpeg → ffprobe/ffmpeg wrappers
│   ├── moment.utils.logging → Logger setup
│   └── moment.utils.system → System helpers
├── moment.bot.main        → Discord bot CLI
│   └── moment.core.discord_bot → Bot implementation
└── moment.mcp.main        → MCP server CLI
    ├── moment.mcp.server  → FastMCP server
    └── moment.mcp.tools   → Tool definitions
```

**Key rule:** `core/` modules never import from `ui/`. `ui/` modules can import from `core/`. Utils are leaf modules (no internal imports).
