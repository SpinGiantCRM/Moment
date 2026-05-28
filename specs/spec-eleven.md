# spec-eleven: Infrastructure

`src/clip_tray/bot/` — Discord bot subcommand
`src/clip_tray/mcp/` — MCP server subcommand

Both optional. Never loaded at startup unless explicitly invoked.

---

## Discord Bot: `clip-tray bot`

```
src/clip_tray/bot/
├── __init__.py
├── main.py        # CLI entry point, bot lifecycle
├── commands.py    # Slash command definitions
└── webhook.py     # Webhook dispatch (called by core/discord_bot.py)
```

- `clip-tray bot` — starts the bot in foreground. `--daemon` flag for background mode (for tray-managed lifecycle). `--token TOKEN` override (default: read from config DB).
- Bot uses `discord.py` (optional dep — `pip install clip-tray[bot]`).
- Slash commands (defined in `commands.py`):
  - `/recent [limit:5]` — last N clips (embed with thumbnail + title + duration + URL)
  - `/stats` — total clips, storage used, uploads today/this week
  - `/search query:[text] [game:optional] [tag:optional]` — search clips, return top 5 as embed list
  - `/clip id:[clip_id]` — full clip details + R2 URL
- Commands query the local SQLite store directly (no network calls). Safe for self-host.
- Configurable auto-start modes (from settings DB key `bot_autostart`):
  - `disabled` (default) — never start. Manual start via tray "Start Discord Bot" or `clip-tray bot`.
  - `auto` — start with app (after GUI init).
  - `auto-delayed` — start 30s after app launch.
  - `manual` — start only when user clicks "Start Discord Bot" in tray or Settings → Bot tab.
- Bot token stored in settings DB (key `bot_token`). Configured in Settings → Bot tab.
- Tray menu shows "Start Discord Bot" / "Stop Discord Bot" dynamically based on bot state.
- Bot lifecycle managed by `AppManager`. Bot runs in its own thread (`asyncio.run` in daemon thread).

## MCP Server: `clip-tray mcp`

```
src/clip_tray/mcp/
├── __init__.py
├── main.py        # CLI entry point, MCP server lifecycle
├── tools.py       # MCP tool definitions
└── server.py      # fastmcp server setup
```

- `clip-tray mcp` — starts MCP server in foreground (stdio transport). `--http` flag for HTTP transport with configurable port (default 8742).
- Uses `fastmcp` (optional dep — `pip install clip-tray[mcp]`).
- Tools exposed (via `@mcp.tool()`):
  - **Query:** `list_clips(status?, game?, folder?, limit?, offset?)` → returns JSON array of clip summaries
  - **Search:** `search_clips(query: str, game?, tag?)` → returns matching clips
  - **Get clip:** `get_clip(clip_id: str)` → full clip details
  - **Stats:** `get_stats()` → total clips, storage, uploads today/week
  - **Pipeline:** `enqueue_encode(clip_id: str)`, `enqueue_upload(clip_id: str)`, `cancel_task(task_id?)`
  - **Capture:** `start_recording(game_name?: str)`, `stop_recording()`, `save_replay(seconds: int)`, `take_screenshot()`
  - **Game profiles:** `list_game_profiles()`, `save_game_profile(profile_json: str)`
  - **Webhooks:** `list_webhooks()`, `test_webhook(webhook_id: str)`
- Tools import `clip_tray.core` modules directly (no REST layer). Run in the MCP server process.
- Server is read-only by default. Pass `--allow-mutations` flag to enable pipeline/capture tools.
- Auto-start mode (config key `mcp_autostart`): `disabled` (default) / `auto` / `manual`.

## Dependency Strategy

```toml
[project.optional-dependencies]
bot = ["discord.py>=2.4"]
mcp = ["fastmcp>=1.0"]
all = ["clip-tray[bot,mcp]"]
```

App installs without optional deps. `clip-tray bot` / `clip-tray mcp` check for missing dep and print clear error: "discord.py not installed. Run: pip install clip-tray[bot]".
