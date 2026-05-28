# spec-seven: Backend Core

`core/game_profiles.py`, `core/discord_bot.py`, `core/import_export.py`

Pure business logic. No GUI imports. Tests required.

---

## game_profiles.py

`GameProfileManager` — CRUD wrapping `store.get_game_profile()`, `store.save_game_profile()`, `store.list_game_profiles()`, `store.delete_game_profile()`.

- Methods: `save(profile)`, `get(game_name)`, `list()`, `delete(game_name)`
- Converts between `GameProfile` dataclass and store rows
- **Game-exit flow detail:** on `GAME_EXITING` signal, the pipeline calls `game_profiles.get(game_name)` → checks `min_duration` (configurable per-profile, default 30s) → if elapsed < min: discard silently; if >= min: auto-save replay + show review card. Configurable per-game: `post_capture_action` field (`card` / `discard` / `editor`).

## discord_bot.py

Full discord.py bot. Webhook dispatch + slash commands.

- `DiscordBot(app_manager: AppManager)` — owns `discord.py.Client` (or `commands.Bot`)
- `start()` — logs in with token from config, connects gateway
- `stop()` — graceful shutdown
- Webhook dispatch: `send_webhook(clip: Clip, webhook: Webhook)` — POST to Discord channel via discord.py, not raw HTTP. Richer embeds.
- Slash commands:
  - `/recent [limit:5]` — last N clips
  - `/stats` — storage, count, uploads today
  - `/search query:[text] [game] [tag]` — search clips
  - `/clip id:[clip_id]` — full clip details + URL
- Async via `asyncio` (discord.py's native model). Uses `asyncio.run()` in a dedicated thread.
- Configurable auto-start (settings: `disabled` / `auto` / `auto-delayed` / `manual`). `auto-delayed` waits 30s after app launch.
- Token stored in settings DB (encrypted? user configures in bot tab of settings dialog).
- Optional dependency: `discord.py` — app continues without it.

## import_export.py

`ImportExport` class.

- `import_file(path: Path, copy: bool = True, profile: str = "game") -> Clip`
  - default: copy file to clips dir, ffprobe metadata, generate thumbnail, insert into store
  - optional re-encode toggle (default off): transcode to H264 NVENC via encoder pipeline
  - presets: Game Mode (H264, fast, high quality), Archive Mode (HEVC, smaller), Streaming Mode (H264, lower bitrate)
  - probe fields extracted: codec, resolution, fps, duration, stream count, audio channels
  - sets `clip_type = IMPORTED`
- `export_clips(clip_ids: list[str], dest: Path)` — copy encoded files to destination folder. Preserves original filenames.
