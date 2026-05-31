# AGENTS.md — Moment AI Agent Briefing

## What is Moment?

Moment is a **GPU-accelerated game clip manager for Linux**. It wraps `gpu-screen-recorder` (GSR) as a managed subprocess, providing a complete pipeline from in-game capture to shareable cloud URL. Think Medal.tv for Linux.

**Package:** `moment` | **Import:** `moment` | **CLI:** `moment`

### Quick Commands

| Command | Description |
|---------|-------------|
| `moment` | Launch GUI |
| `moment --minimized` | Start in tray |
| `moment --settings` | Open settings dialog |
| `moment --open-encoded` | Open encoded clips folder |
| `moment bot` | Start Discord bot |
| `moment mcp` | Start MCP server for AI agent access |

---

## Core Architectural Principles

1. **GSR as subprocess controller** — Moment manages `gpu-screen-recorder` as a thin wrapper; it does NOT reimplement screen capture.
2. **Pipeline architecture** — Clips flow through a priority task queue: Watcher → Encode → Upload → Notify.
3. **PyQt6 dark theme** — ONLYOFFICE Modern Dark inspired design with floating island toolbars.
4. **Encrypted at rest** — SQLite database (pysqlcipher3) with keys in the OS keyring. No plaintext fallback.
5. **Game-aware pausing** — GPU-intensive pipeline tasks pause when a game is active to avoid stealing NVENC sessions.
6. **Best-effort services** — Core services (Store, Config, Pipeline) fail gracefully; GUI launches without them and shows an error banner.
7. **No GUI in core** — The `moment/core/` directory must never import from PyQt6.

---

## File Organization

```
src/moment/
├── core/                  # Business logic, no GUI imports allowed
│   ├── config.py          # Key-value settings (SQLite-backed)
│   ├── store.py           # SQLite persistence facade (~266 lines)
│   ├── models.py          # Pure dataclasses & enums
│   ├── event_bus.py       # Centralized QObject signal bus
│   ├── encryption.py      # Fernet encrypt/decrypt helpers
│   ├── migrations.py      # Legacy JSON import, directory renames
│   ├── pipeline.py        # Task queue & worker threads
│   ├── encoder.py         # NVENC/VAAPI ffmpeg encoding
│   ├── uploader.py        # rclone-based cloud upload
│   ├── thumbnail.py       # Thumbnail generation
│   ├── gsr_controller.py  # GSR subprocess management
│   ├── gsr_watcher.py     # GSR output directory watcher
│   ├── recorder_controller.py # Recording lifecycle
│   ├── hotkey_daemon.py   # Hotkey listening daemon
│   ├── noise_suppression.py # RNNoise integration
│   ├── corruption.py      # Corrupt clip detection
│   ├── game_monitor.py    # Game process detection
│   ├── game_profiles.py   # Per-game recording profiles
│   ├── bookmarker.py      # Session bookmark management
│   ├── screenshot.py      # Screenshot capture
│   ├── retention.py       # Automatic clip deletion by age
│   ├── import_export.py   # Clip import/export operations
│   ├── discord_bot.py     # Discord bot integration
│   ├── repositories/      # Domain persistence layer (refactored from monolithic store)
│   │   ├── base.py        # Connection helpers, schema, migration framework (run_migrations)
│   │   ├── clip_repo.py
│   │   ├── tag_repo.py
│   │   ├── folder_repo.py
│   │   ├── bookmark_repo.py
│   │   ├── profile_repo.py
│   │   ├── webhook_repo.py
│   │   ├── task_repo.py
│   │   └── settings_repo.py
│   └── __init__.py
│
├── ui/                    # PyQt6 GUI components
│   ├── app.py             # AppManager — bootstrap & lifecycle
│   ├── main_window.py     # QMainWindow with page stack
│   ├── tray.py            # System tray icon
│   ├── resources.py       # Stylesheet, icons, fonts
│   ├── pages/             # Page views
│   │   ├── grid_page.py   # Clip grid with search/filter
│   │   ├── player_page.py # Video player
│   │   ├── recording_page.py # Recording controls
│   │   ├── stats_page.py  # Aggregate statistics
│   │   ├── trash_page.py  # Soft-deleted clips
│   │   └── webhook_page.py # Webhook management
│   ├── dialogs/           # Modal dialogs
│   │   ├── settings_dialog.py
│   │   ├── trim_dialog.py
│   │   ├── tag_dialog.py
│   │   ├── game_profile_dialog.py
│   │   └── about_dialog.py
│   ├── widgets/           # Reusable widgets
│   │   ├── toast.py       # Stacking notifications
│   │   ├── search_bar.py
│   │   ├── timeline_editor.py
│   │   ├── audio_mixer.py
│   │   ├── overlay.py     # GSR overlay
│   │   ├── pip_window.py  # Picture-in-picture
│   │   └── ... (14 widgets total)
│   ├── editor/            # Video editor module
│   │   ├── editor_window.py
│   │   ├── timeline_panel.py
│   │   ├── filter_panel.py
│   │   ├── merge_panel.py
│   │   ├── music_panel.py
│   │   └── gif_exporter.py
│   └── services/
│       └── global_hotkey.py # KDE global shortcut registration
│
├── utils/                 # Utility modules
│   ├── ffmpeg.py          # ffmpeg/ffprobe wrappers
│   ├── logging.py         # Logging configuration
│   ├── system.py          # System helpers
│   └── subprocess.py      # Subprocess helpers
│
├── bot/                   # Discord bot
│   ├── main.py            # CLI entry point for `moment bot`
│   └── __init__.py
│
├── mcp/                   # MCP server for AI agent access
│   ├── main.py            # CLI entry point for `moment mcp`
│   ├── server.py          # FastMCP server
│   └── tools.py           # Tool definitions
│
├── __init__.py            # Version
├── __main__.py            # `python -m moment` entry point
└── main.py                # CLI dispatch (gui/bot/mcp)
```

---

## Files That Should NEVER Be Modified

| File | Reason |
|------|--------|
| `src/moment/__init__.py` | Only `__version__` string — bump on release |
| `src/moment/__main__.py` | Single-line dispatch to `main.py` |
| `install/save-replay.sh` | Shell script used by GSR overlay fallback — must remain standalone |
| `install/moment.desktop` | Desktop entry file — must match freedesktop.org spec |
| `install/moment-bot.service` | systemd unit — must remain valid |
| `LICENSE` | GPL v3 — never change |
| `.github/pull_request_template.md` | PR template |
| `.github/workflows/ci.yml` | CI pipeline |
| `.github/workflows/release.yml` | Release pipeline |

**Files with high modification risk** (be extra careful):
- `src/moment/core/models.py` — used everywhere; changing a field affects ALL consumers
- `src/moment/core/config.py` — key whitelist enforcement; adding keys requires updating `_ALLOWED_KEYS`
- `src/moment/core/repositories/base.py` — shared schema, migration framework (run_migrations), connection helpers
- `src/moment/core/repositories/*.py` — each repo is the single source of truth for its table's CRUD

---

## How Features Are Organized

### Feature: Clip Capture → Upload Pipeline

```
GSR writes MKV → GSRWatcher → Store.insert_clip()
  → Pipeline.enqueue(ENCODE) → ffmpeg NVENC → encoded.mp4
  → Pipeline.enqueue(UPLOAD) → rclone copy → cloud URL
  → Pipeline.enqueue(THUMBNAIL) → ffmpeg frame extract → .jpg
  → EventBus signals → Toast notification → Grid page updates
```

Key files: `gsr_controller.py`, `gsr_watcher.py`, `recorder_controller.py`, `pipeline.py`, `encoder.py`, `uploader.py`, `thumbnail.py`, `event_bus.py`

### Feature: Discord Bot

```
Slash command → DiscordBot handler → Store query → Embed response
  → Webhook dispatch on new clip → Discord channel message
```

Key files: `discord_bot.py`, `bot/main.py`

### Feature: MCP Server

```
HTTP POST /tools → Bearer auth check → Store operation → JSON response
  (--allow-mutations flag enables writes; without it: read-only)
  stdio transport also available
```

Key files: `mcp/server.py`, `mcp/tools.py`

### Feature: Video Editor

```
Timeline panel → EditProfile construction → Store.save_edit_profile()
  → Merge/trim/speed/filters → ffmpeg filter graph → rendered output
```

Key files: `editor/*.py`, `models.py` (EditProfile, SegmentEdit, FilterConfig)

---

## Testing Workflow

**Always follow this order when modifying code:**

1. **Write/update tests first** in `tests/test_*.py` (matching the module under test)
2. **Run specific tests** to validate:
   ```bash
   python -m pytest tests/test_<module>.py -x --tb=short -q
   ```
3. **Run the full suite** before committing:
   ```bash
   make test
   ```
4. **Run the linter**:
   ```bash
   make lint
   ```

**Test fixtures** are defined in `tests/conftest.py`:
- `store` fixture: In-memory SQLite with mocked encryption
- `qapp` fixture: Session-scoped QApplication (offscreen)
- `sample_clip` fixture: Pre-built clip dict
- Fernet cache is pre-seeded with a test key (bypasses keyring)

**Testing patterns to follow:**
- Use `unittest.mock.patch` to mock external dependencies (GSR, ffmpeg, rclone)
- Use `pytest.fixture` for shared state
- Never test against a real filesystem or database — use `tmp_path` / `tempfile`
- UI tests use `QT_QPA_PLATFORM=offscreen`
- Test both success paths AND error paths

---

## Coding Standards

### Python Style
- **Type hints** required on all function signatures (`from __future__ import annotations`)
- **Docstrings** for public classes and methods (Google-style)
- **Line length**: 100 chars
- **Formatting**: ruff (see `pyproject.toml`)
- **No bare `except:`** — always specify exception types or use `except Exception:`
- **No `# nosec`** without a comment explaining why

### Imports
- Standard library first, then third-party, then local
- Use `TYPE_CHECKING` for type-only imports to avoid circular imports
- `from __future__ import annotations` at the top of every module

### Naming
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- Module-level "private" globals: `_leading_underscore`

### Signal/Slot Pattern (PyQt6)
```python
class Foo(QObject):
    something_happened = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.something_happened.connect(self._on_something)

    def _on_something(self, value: str) -> None:
        ...
```

---

## Common Pitfalls

### 1. **Pysqlcipher3 Mandatory**
The Store will NOT open without `pysqlcipher3` and `keyring`. Tests mock `_connect_encrypted` and `_run_encryption_health_check` to bypass this.

### 2. **Fernet Key Management**
Webhook URLs are encrypted with a Fernet key stored in the OS keyring. `Store.reset_fernet_cache()` MUST be called between tests to avoid cross-test pollution. The conftest.py fixture handles this.

### 3. **Thread Safety**
Pipeline workers run in background threads. UI updates MUST go through Qt signals (`pyqtSignal`), never direct calls from worker threads.

### 4. **Database Migrations**
The migration framework uses a `schema_version` table with numbered, ordered migrations defined in `base.py` (`_MIGRATIONS` list). New migrations:
1. Add a `_migration_NNN_name()` function in `base.py` that accepts `sqlite3.Connection`
2. Append `("NNN_name", _migration_NNN_name)` to the `_MIGRATIONS` list
3. `run_migrations()` runs them in order inside transactions

### 5. **Config Key Whitelist**
`Config.set()` rejects unknown keys. You MUST add new keys to `_ALLOWED_KEYS` or `_ALLOWED_PREFIXES` in `config.py`.

### 6. **Game Monitor Pausing**
The `GameMonitor` pauses the pipeline when a game process is detected. This affects encoding and thumbnail generation. Uploads are NOT paused.

### 7. **Soft Delete vs Hard Delete**
Clips use soft-delete (`deleted_at` timestamp set, data preserved). Hard delete (`Store.delete_clip(soft=False)`) is only for the "Empty Trash" operation.

### 8. **Event Bus**
Core components emit on `EventBus` instead of accepting raw callbacks. The UI layer connects bus signals to Qt slots for thread-safe delivery. Never `import` from `ui/` in a core module to emit signals — use `EventBus` from a passed reference.

---

## Security Requirements

1. **Encryption mandatory** — pysqlcipher3 for DB, Fernet for webhook URLs, keyring for all secrets
2. **No plaintext fallback** — encryption failures are hard errors (RuntimeError), not silent downgrades
3. **Config key whitelist** — prevents arbitrary config writes via `_ALLOWED_KEYS`
4. **Path containment** — `path_*` config values must resolve within `$HOME` or `/tmp`
5. **Webhook URL validation** — must be HTTPS (`_is_secure_url()`)
6. **DB file permissions** — `0o600` (owner-only)
7. **Clipboard timeout** — URLs auto-clear after 60 seconds
8. **PID-based signaling** — `save-replay.sh` uses `pgrep` + `kill`, not `killall`
9. **MCP auth** — ALL HTTP endpoints require Bearer token; scoped tokens (read-only vs. read-write via `--allow-mutations`)
10. **Log redaction** — secrets (tokens, keys, URLs) are redacted in logs

---

## Performance Requirements

| Metric | Target |
|--------|--------|
| Startup time | <500ms |
| Idle memory | <100MB RSS |
| Encoding memory | <200MB RSS |
| Thumbnail cache | 250 entries LRU (lazy loaded) |
| Thread pool | 1 encode + 2 upload + 1 thumbnail |
| GPU semaphore | 1 concurrent encode (safe default) |
| UI responsiveness | All DB reads eventually async |

---

## MCP Server Details

- **HTTP**: `127.0.0.1:8742` (configurable via `--port`)
- **Stdio**: stdin/stdout JSON-RPC
- **Auth**: Bearer token required on ALL endpoints via `--api-token` or `MOMENT_MCP_TOKEN` env var
- **Scope**: `--allow-mutations` flag enables write operations; without it, read-only
- **Endpoints**: list/search/get clips, get stats, list game profiles, list webhooks, enqueue encode/upload, save game profile, test webhook

## Discord Bot Details

- **Token**: Stored in OS keyring only (no env var fallback)
- **Commands**: `/clip`, `/search`, `/recent`, `/stats`
- **Auth**: Role-based access control (`discord_allowed_roles`)
- **Rate limiting**: SQLite-backed persistent rate limiting
- **Webhook dispatch**: Automatic when new clip is uploaded
