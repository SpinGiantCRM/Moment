# Development

## Setup

```bash
git clone https://github.com/SpinGiantCRM/Moment.git
cd Moment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Architecture

```
src/moment/
├── core/               # Business logic — NO GUI imports
│   ├── store.py        # SQLite database (WAL mode)
│   ├── config.py       # Config dataclass + YAML persistence
│   ├── encoder.py      # ffmpeg encoding pipeline
│   ├── uploader.py     # rclone uploads
│   ├── pipeline.py     # Orchestrates encode→upload→notify
│   ├── gsr_controller.py  # GSR process lifecycle
│   ├── gsr_watcher.py     # Inotify file watcher for new clips
│   ├── recorder_controller.py  # Legacy subprocess recorder
│   ├── game_profiles.py # Per-game recording profiles
│   ├── models.py       # Dataclasses (Clip, Game, etc.)
│   ├── thumbnail.py    # Thumbnail generation
│   ├── corruption.py   # Corruption detection/recovery
│   └── discord_bot.py  # Discord bot (optional)
├── ui/
│   ├── app.py          # Application bootstrap, tray, CLI parser
│   ├── pages/          # Full-page views in the main window
│   ├── dialogs/        # Modal dialogs (Settings, About, etc.)
│   └── widgets/        # Reusable widgets (overlay, toolbar, etc.)
│       └── overlay.py  # In-game floating overlay
├── utils/
│   ├── ffmpeg.py       # ffmpeg/ffprobe wrappers, encoder detection
│   ├── system.py       # System helpers (which, cpu count, etc.)
│   └── logging.py      # Logging setup
└── bot/                # Discord bot CLI entry point
```

### Key constraint

`core/` must never import from `ui/`. This keeps the business logic testable without a display server.

## Threading model

| Thread | GPU-bound | Pauses during gameplay |
|---|---|---|
| Encode (1×) | Yes (NVENC) | Yes (configurable) |
| Upload (N×) | No | No |
| Thumbnail (1×) | Yes | Yes |

GPU resources are serialized via `threading.BoundedSemaphore(1)` in encoder.py.

## Data flow

```
GSR (-k mode) ──► MKV writes (SIGUSR1) ──► Watcher ──► Store ──► Thumbnail ──► Encode ──► Upload
```

GSR records to a circular buffer in GPU memory. On save signal, it writes an MKV to disk. The watcher (inotify) detects the file. Moment imports metadata, generates a thumbnail, queues the encode job, and optionally uploads.

## Testing

```bash
# Run all tests
pytest tests/ -x --tb=short

# With coverage
pytest --cov=src/moment tests/ --cov-report=term-missing

# GUI tests (offscreen)
QT_QPA_PLATFORM=offscreen pytest tests/
```

Testing conventions:
- Use `pytest-qt` with `QT_QPA_PLATFORM=offscreen` for UI tests
- Mock all ffmpeg/ffprobe subprocess calls
- Use `tmp_path` fixtures for temp DB and config files
- The `conftest.py` provides `store_with_clips` fixture

## Code style

- Format: `ruff format .`
- Lint: `ruff check .`
- Security: `bandit -r src/`
- Type hints required on all public functions

## CI

GitHub Actions runs on every push:
1. **Lint** — ruff check + format
2. **Test** — pytest with xvfb-run, matrix across Python 3.11-3.13
3. **Security** — bandit scan
4. **Coverage** — uploaded as artifact (not gated yet)

## Making a release

```bash
make release VERSION=0.2.0  # bumps, commits, tags, builds
make dist                    # builds wheel + sdist
```

## Specs

Implementation specs live in [.opencode/specs/](https://github.com/SpinGiantCRM/Moment/tree/master/.opencode/specs):

| # | Spec | Status |
|---|---|---|
| 01 | App icon + desktop entry | 📝 Draft |
| 02 | GitHub CI | 📝 Draft |
| 03 | Configurable file paths | 📝 Draft |
| 04 | GSR integration (replay buffer, overlay, hotkey) | 📝 Draft |
| 05 | GPU agnostic encoding | 📝 Draft |
| 06 | UI polish | 📝 Draft |
| 07 | Test coverage | 📝 Draft |
| 08 | Deployment (PKGBUILD, bot service, release) | 📝 Draft |
