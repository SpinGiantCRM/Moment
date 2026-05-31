# Moment — Project Knowledge

GPU-accelerated game clip manager for Linux. Wraps `gpu-screen-recorder` (GSR) as a managed subprocess. Python 3.11+ / PyQt6 / NVENC.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| **Package** | `moment` |
| **CLI** | `moment` (GUI), `moment import/export`, `moment diagnose`, `moment bot`, `moment mcp` |
| **Source** | `src/moment/` (80 files, ~14K lines) |
| **Tests** | `tests/` (70 files, ~24K lines) |
| **Config** | `pyproject.toml` — ruff, pytest |
| **Secrets** | OS keyring only (no env vars, no config table) |

## Architecture (2-second summary)

```
Hotkey/UI → GSRController (capture) → Watcher (detect) → Pipeline (encode/upload/thumbnail)
                ↑                                              ↓
            GameMonitor                                   Store (SQLCipher DB)
                ↓                                              ↓
            Pause GPU tasks on game                     Disk + Cloud (rclone)
```

- **`core/`** — Business logic (NEVER imports PyQt6)
- **`ui/`** — PyQt6 GUI (pages, dialogs, widgets, editor)
- **`utils/`** — ffmpeg, logging, system helpers
- **`bot/`** — Discord bot (optional)
- **`mcp/`** — MCP server (optional)

## Critical Rules

1. **Encryption is mandatory** — sqlcipher3 + keyring required. No plaintext fallback.
2. **No GUI in core** — `core/` never imports from PyQt6. Thread-safe signals only.
3. **Config whitelist** — `_ALLOWED_KEYS` in `config.py`; unknown keys are rejected.
4. **DB migrations** — `_MIGRATIONS` list in `base.py`, numbered ordered migrations in `schema_version` table.
5. **Test patterns** — `pytest`, mock externals, `Store.reset_fernet_cache()` between tests.

## Where to Look

| Task | Start Here |
|------|-----------|
| Add a field to Clip | `models.py` → `base.py` (SCHEMA_SQL) + repo CRUD + `_MIGRATIONS` entry |
| New pipeline stage | `pipeline.py` (task types + workers) |
| New UI page | `ui/pages/` + `main_window.py` (register in page stack) |
| New widget | `ui/widgets/` |
| New CLI command | `main.py` (argparse dispatch) |
| New MCP tool | `mcp/tools.py` + `mcp/server.py` (register endpoint) |
| New Discord command | `discord_bot.py` (slash command handler) |
| Store/repo interaction | `store.py` delegates to `repositories/*.py` for CRUD |

## Docs Map

→ **AGENTS.md** — Full project briefing (architecture, standards, pitfalls)
→ **ARCHITECTURE.md** — System flow diagrams, thread model, encryption
→ **SECURITY.md** — Encryption details, credential management, auth
→ **CONTRIBUTING.md** — Dev setup, PR process, testing guidelines
→ **TRUTH.md** — Complete feature inventory + aspirational state
→ **docs/** — Detailed guides (getting-started, storage-providers, database schema)

## Resolved Issues

1. **pysqlcipher3 → sqlcipher3** (May 2026) — `pysqlcipher3` uses removed C API functions (`PyObject_AsCharBuffer`, `_PyLong_AsInt`) and fails to build on Python 3.13+. `sqlcipher3>=0.6` has prebuilt wheels for CPython 3.9–3.14 and is API-compatible (`import sqlcipher3.dbapi2 as sqlcipher`). Swapped in `base.py` and `pyproject.toml`.
