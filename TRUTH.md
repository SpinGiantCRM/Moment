# Moment — Truth

GPU-accelerated game clip manager for Linux. The totality of what this app is, does, and strives to do.

## Identity

Moment is a desktop application that wraps `gpu-screen-recorder` as a thin subprocess controller, providing a seamless pipeline from in-game recording to a shareable cloud URL. It is the Medal.tv equivalent for Linux — a system tray app that lives in the background, captures your gameplay, and gets out of your way.

**Package:** `moment` | **Binary:** `moment` | **Import:** `moment`

---

## 1. Capture System

### 1.1 GPU Screen Recorder Integration
- Manages `gpu-screen-recorder` as a managed subprocess
- Launch, monitor, and graceful shutdown of GSR
- Replay buffer mode (instant replay, circular buffer in VRAM)
- SIGUSR1-based buffer save (`save-replay.sh`)
- Configurable recording directory
- Crash detection and auto-restart with circuit breaker

### 1.2 Hotkey Control
- F8: Save 30-second replay
- F9: Save 60-second replay
- F10: Open settings
- KDE global shortcut registration via `kglobalaccel`
- Configurable hotkey bindings
- Per-game hotkey profiles

### 1.3 Bookmark System
- Mid-session bookmark markers (saved to database with timestamp)
- Bookmark metadata (label, notes, game context)
- Bookmark → clip navigation in player

### 1.4 Screenshot Capture
- Instant screenshot via ffmpeg x11grab
- Per-game screenshot settings
- Dedicated hotkey
- **Striving toward:** PipeWire/xdg-desktop-portal capture for Wayland

---

## 2. Pipeline

### 2.1 Watcher
- Filesystem monitoring for new MKV files from GSR
- mtime stability detection (10s interval)
- GSR-specific watcher for output directory
- **Striving toward:** End-to-end wiring (GSR → import → encode → upload → notify)

### 2.2 Encoding
- NVENC hardware-accelerated encoding via ffmpeg
- H.264/H.265/AV1 codec support
- Configurable CRF, preset, resolution, bitrate
- GPU semaphore (single encode at a time — safe default)
- **Striving toward:** Configurable NVENC concurrency (modern GPUs support 2-3+ sessions)

### 2.3 Thumbnail Generation
- ffmpeg-based frame extraction at configurable seek point
- LRU cache (max 250 entries)
- Lazy load on scroll in grid view
- Async generation in dedicated worker thread
- **Striving toward:** Batch generation, pipeline-stage thumbnail creation

### 2.4 Upload
- rclone-based upload to any cloud provider
- Concurrent upload worker pool (configurable N)
- Circuit breaker (stops retry loops on persistent failure)
- **Striving toward:** Upload progress reporting, backpressure

### 2.5 Task Queue
- Thread-safe `queue.Queue` pipeline
- Worker threads: encode (1), upload (N), thumbnail (1)
- Graceful shutdown with worker join (30s timeout)
- **Striving toward:** maxsize backpressure, persist queue to SQLite

---

## 3. Storage & Data

### 3.1 SQLite Database
- WAL mode at `~/.config/moment/clips.db`
- 13 tables: clips, edit_profiles, tags, clip_tags, url_history, webhooks, webhook_log, settings, folders, folder_clips, game_profiles, bookmarks, pip_cache
- Soft-delete with `deleted_at` timestamp
- DB file permissions: 0o600 (owner-only)
- **Striving toward:** Mandatory encryption (pysqlcipher3), schema versioning/migration framework, read-write lock, separate read connection

### 3.2 Config System
- Key-value settings table
- Config key whitelist (prevents arbitrary config writes)
- Path override support for data/config/temp directories
- **Striving toward:** Migration from settings table to keyring for secrets

### 3.3 Import/Export
- Import clips from filesystem (copy or reference mode)
- Export clips to user-chosen destination
- MIME type validation (python-magic or file(1))
- **Striving toward:** Metadata scrubbing on import (`ffmpeg -map_metadata -1`), proper path containment with `commonpath()`

### 3.4 Retention
- Automatic clip deletion by age (source files, encoded files)
- Configurable retention periods per clip type
- Protected clips exclusion (`protect_from_retention` flag)
- **Striving toward:** Pipeline state cross-check before deletion, batch SQL operations instead of loading all clips

---

## 4. GUI (PyQt6)

### 4.1 Main Window
- Dark theme (ONLYOFFICE Modern Dark inspired)
- Floating island toolbars (rounded, elevated, shadow)
- Left nav with page buttons: Grid, Player, Recording, Stats, Trash, Webhooks
- Status bar with pipeline activity feedback

### 4.2 Pages
- **Grid Page:** Filterable, paginated clip grid. Sort by date/game/size. Selection mode (batch operations). Search bar with game/tag/title filtering.
- **Player Page:** Video playback, clip metadata panel, action buttons (favorite, share, delete, edit)
- **Stats Page:** Aggregate statistics — total clips, storage, today/week counts, per-game breakdown, upload history
- **Trash Page:** Soft-deleted clips with restore/permanent-delete
- **Webhook Page:** Webhook CRUD, test dispatch, activity log
- **Recording Page:** Recording controls, status, GSR connection state
- **Striving toward:** Async DB reads off UI thread (skeleton/loading states)

### 4.3 Dialogs
- **Settings Dialog:** General, Recording, Upload, Webhook, About tabs
- **Trim Dialog:** ffmpeg-based clip trimming with preview
- **Tag Dialog:** Multi-tag assignment and management
- **Game Profile Dialog:** Per-game recording/encoding profile configuration
- **About Dialog:** Version, credits, dependency info
- **Merge Dialog:** Clip concatenation
- **Import Dialog:** File picker + import options
- **Striving toward:** Confirmation dialogs for destructive actions (batch delete, trash purge)

### 4.4 Widgets
- **Toast:** Bottom-right stacking notifications. Types: success(5s), info(4s), warning(6s), error(8s)
- **Clip Delegate:** Custom grid card rendering for clip data
- **Context Menu:** Right-click actions on clips
- **Hover Preview:** Thumbnail popup on grid hover
- **Search Bar:** Real-time clip filtering
- **Progress Ring:** Indeterminate/repeating animation for loading states
- **Skeleton Card:** Placeholder during async data loading
- **Processing Banner:** Pipeline activity overlay
- **Review Card:** Post-capture rating + metadata widget
- **PIP Window:** Floating picture-in-picture player
- **Audio Mixer:** Per-track volume/gain control
- **Timeline Editor:** Temporal clip manipulation
- **Transition Picker:** Between-clip transition selection
- **Striving toward:** Native Wayland notifications, accessible toasts, progress bars for long operations

### 4.5 Editor Module
- **Timeline Panel:** Multi-track clip editing, trimming, rearranging
- **Merge Panel:** Clip concatenation with transition selection
- **GIF Exporter:** Clip → GIF conversion with size/speed control
- **Music Panel:** Background audio overlay
- **Filter Panel:** Visual filters (color, speed, crop)

### 4.6 System Tray
- Background daemon presence
- Recent clips submenu (up to 3)
- Quick actions: Save replay, Screenshot, Bookmark
- Toggle window visibility
- **Striving toward:** Mature all tray actions (some are log-only stubs), copy-last-URL on middle-click

### 4.7 Visual Design
- 17 color tokens (dark palette)
- 8 design rules (flat, no borders, outline icons, floating islands)
- Outline SVG icons (24x24, monoline, 1.5-2px stroke, 78% opacity)
- **Striving toward:** WCAG 2.1 AA contrast compliance, high-contrast theme support, screen reader accessibility (accessible names, roles, descriptions), proper focus management

---

## 5. Security (Aspirational State)

Moment is audited at 38/100 and is **striving toward** production-ready security:

### 5.1 Encryption
- **Sought:** Mandatory pysqlcipher3 for SQLite — hard fail on missing dep
- **Sought:** Remove all plaintext fallback paths in encryption
- **Sought:** Store encryption keys in OS keyring (never alongside ciphertext)
- **Sought:** Hard-fail webhook URL encryption (no silent plaintext fallback)

### 5.2 Authentication
- **Sought:** Authenticate ALL MCP HTTP endpoints (not just mutations)
- **Sought:** Constant-time auth comparison (`hmac.compare_digest()`)
- **Sought:** Scoped tokens (read-only vs. mutation)
- **Sought:** Server-side clip visibility enforcement (owner_id from token, not caller input)

### 5.3 Credential Management
- **Sought:** Keyring-only Discord token storage (no env var sourcing)
- **Sought:** Retry keyring migration on every startup
- **Sought:** No MCP token in config DB (keyring or session-only)

### 5.4 Logging & Monitoring
- **Sought:** Comprehensive secret redaction (tokens, keys, URLs, paths)
- **Sought:** Audit logging for sensitive operations
- **Sought:** Metrics/health endpoint

### 5.5 Hardening
- **Sought:** Remove `MOMENT_BYPASS_WEBHOOK_RATE_LIMIT` env var
- **Sought:** PID-based signaling (no broad `killall`)
- **Sought:** Clipboard timeout for sensitive URLs
- **Sought:** File integrity monitoring for DB
- **Sought:** Sandbox ffmpeg subprocesses
- **Sought:** SBOM + dependency scanning in CI

---

## 6. Integrations

### 6.1 Discord Bot (Optional)
- Slash commands: `/clip`, `/search`, `/recent`, `/stats`
- Webhook dispatch on new clip (title, game, duration, thumbnail, R2 URL)
- Role-based access control
- Discord activity presence (rich presence)
- **Striving toward:** Opt-in R2 URL inclusion per webhook, mandatory role enforcement

### 6.2 MCP Server (Optional)
- HTTP on `127.0.0.1:8742` + stdio transport
- Tools: list/search/get clips, get stats, list game profiles, list webhooks, enqueue encode/upload, save game profile, test webhook
- Auth token on mutation endpoints
- **Striving toward:** Auth on all endpoints, scoped read-only token, metrics/health endpoint

### 6.3 Cloud Storage (via rclone)
- R2, S3, B2, GCS, Wasabi, Dropbox, Google Drive, MinIO, SFTP/NAS
- Configurable bucket/path/region
- Environment variable configuration

---

## 7. Infrastructure

### 7.1 Installation
- `install/install.sh` with `--user` (default) and `--system` (sudo) modes
- Desktop entry (`moment.desktop`) with app launcher integration
- SVG app icon with PNG renders at 48/64/128/256px
- Systemd service (`moment-bot.service`) for headless daemon mode
- PKGBUILD for Arch Linux
- `save-replay.sh` for hotkey-triggered buffer dump

### 7.2 CI/CD
- GitHub Actions CI: lint (ruff), test (pytest + xvfb-run), security (bandit)
- Python 3.11-3.13 matrix
- Release workflow (PyPI publishing)
- Pull request template

### 7.3 Build System
- pyproject.toml with setuptools
- Makefile with dev commands
- `pip install moment[bot,mcp,encryption]` extras

---

## 8. Architecture (Aspirational State)

Moment is audited at 2.9/10 architecturally and is **striving toward**:

- **Domain repositories:** Split 1650-line store.py into ClipRepository, WebhookRepository, ProfileRepository, etc.
- **Event bus:** Centralized signal-based bus replacing callback spaghetti
- **Dependency injection:** Eliminate all `set_*_config()` module-level globals
- **Async I/O:** asyncio for rclone uploads, webhooks; dedicated thread pool for CPU work
- **Structured logging:** JSON output, correlation IDs, no bare `except: pass`
- **Migration framework:** Schema version table with numbered, ordered migrations
- **Test infrastructure:** PyTest with minimum 40% coverage before production
- **Graceful degradation:** User-visible warnings for missing optional deps

---

## 9. Reliability (Aspirational State)

- **Timer chain resilience:** Keepalive heartbeat; handler errors don't kill the timer
- **Orphan child cleanup:** `atexit` + signal handlers for SIGTERM/SIGSEGV cleanup
- **Connection management:** Persistent config connection, SQLITE_BUSY retry with backoff
- **Thread safety:** `collections.deque` for restart timestamps, guard `start()`/`stop()` with state machine
- **Crash callbacks:** Never invoke callbacks while holding a lock (deadlock prevention)

---

## 10. Compatibility

### Platforms
- **Primary:** Linux (KDE Plasma, GNOME, any X11/Wayland compositor)
- **Capture:** NVIDIA NVENC (primary), VAAPI (fallback), software (last resort)
- **Display:** X11 (current), Wayland (sought)

### Dependencies
- **Required:** Python 3.11+, PyQt6, ffmpeg/ffprobe, rclone, gpu-screen-recorder
- **Optional:** discord.py (bot), fastmcp (MCP), keyring (secrets), pysqlcipher3 (encryption), python-magic (MIME), RNNoise (noise suppression)

---

## 11. Performance Targets

| Metric | Current | Target |
|--------|---------|--------|
| Startup time | — | <500ms |
| Idle memory | — | <100MB RSS |
| Encoding memory | — | <200MB RSS |
| Thumbnail cache | 250 LRU | 250+ with lazy loading |
| Thread pool | 1 encode + N upload + 1 thumb | Same, with backpressure |
| UI responsiveness | Blocking SQLite reads | All reads async |

---

## 12. Non-Goals

- Reimplementing screen capture (we wrap GSR)
- Windows/macOS support (Linux-only desktop app)
- Video transcoding beyond NVENC/VAAPI (no software encoding)
- Social network / feed (no timeline, no followers)
- Mobile app
- Game overlay (GSR provides the in-game overlay)
