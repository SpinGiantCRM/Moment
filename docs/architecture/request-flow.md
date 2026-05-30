# Request Flows

## Capture Flow (Hotkey → Cloud URL)

```
Hotkey pressed (Alt+Z)
  │
  ▼
GlobalHotkeyManager.triggered → Overlay.toggle()
  │
  ├─ User selects duration (30s / 60s / custom)
  │   │
  │   ▼
  │   GSRController.save_replay()
  │     │
  │     ├─ Sends SIGUSR1 to gpu-screen-recorder process
  │     ├─ GSR dumps VRAM buffer to MKV file
  │     └─ File lands in ~/Videos/Moment/
  │
  └─ User opens Moment UI
      │
      ▼
      MainWindow._create_window()
        │
        ├─ RecordingPage (default)
        ├─ GridPage (clip list)
        └─ PlayerPage (playback)
```

## Import Flow (Filesystem → Database)

```
GSRWatcher._on_new_clip(path: Path)
  │
  ├─ ffprobe metadata extraction
  │   ├─ duration, file_size, video_codec
  │   ├─ fps, resolution
  │   └─ audio streams (game vs mic)
  │
  ├─ Clip() creation with UUID
  │
  ├─ Store.insert_clip(clip)
  │
  ├─ Pipeline.enqueue(ENCODE task, priority=10)
  │
  └─ Pipeline.enqueue(THUMBNAIL task, priority=5)
```

## Encode Flow (MKV → MP4)

```
Pipeline._encode_worker()
  │
  ├─ Wait for GPU semaphore (1 concurrent encode)
  │
  ├─ Probe metadata (if not already probed)
  │
  ├─ Load EditProfile (trim, speed, filters, overlays)
  │
  ├─ Build ffmpeg command:
  │   ffmpeg -hwaccel cuda -i input.mkv
  │     -c:v h264_nvenc -preset p7 -cq 23
  │     -vf "trim=...,setpts=..."  (if edits exist)
  │     -c:a aac -b:a 128k
  │     output.mp4
  │
  ├─ Execute ffmpeg (blocking, GPU-bound)
  │
  ├─ Update clip.status = DONE
  │
  └─ Pipeline.enqueue(UPLOAD task, priority=1)
```

## Upload Flow (Local → Cloud)

```
Pipeline._upload_worker()
  │
  ├─ Read encoded file path
  │
  ├─ Build rclone command:
  │   rclone copy output.mp4 remote:bucket/path/
  │
  ├─ Execute rclone (IO-bound, non-blocking for UI)
  │
  ├─ Construct public URL (from config)
  │
  ├─ Update clip.status = UPLOADED
  │   clip.r2_url = "https://..."
  │   clip.uploaded_at = now
  │
  └─ Callbacks:
      ├─ GUI Toast: "Clip uploaded → URL"
      ├─ Discord webhook dispatch (if configured)
      └─ MCP notification (if connected)
```

## Search Flow (User Query → Results)

```
GridPage.search(query: str)
  │
  ├─ Store.list_clips(search=query, ...)
  │   │
  │   ├─ SQL: WHERE (title LIKE '%query%' OR stem LIKE '%query%')
  │   │       AND deleted_at IS NULL
  │   │       ORDER BY recorded_at DESC
  │   │       LIMIT 50 OFFSET 0
  │   │
  │   └─ Returns list[Clip] with tags joined
  │
  ├─ Update GridPage model
  │
  └─ Render clip cards (lazy thumbnails)
```

## Thumbnail Flow (Video → JPEG)

```
Thumbnailer.generate(clip)
  │
  ├─ Check LRU cache (max 250 entries)
  │   ├─ Cache hit → return cached path
  │   └─ Cache miss → continue
  │
  ├─ Build ffmpeg command:
  │   ffmpeg -ss 5 -i input.mkv -vframes 1 -q:v 5 thumb.jpg
  │
  ├─ Execute ffmpeg (GPU-bound, serializer via semaphore)
  │
  ├─ Save to ~/.local/share/moment/thumbnails/
  │
  ├─ Update LRU cache
  │
  └─ Signal UI to update (lazy load on scroll)
```

## Discord Bot Flow (Slash Command → Response)

```
DiscordBot.on_ready()
  │
  ├─ Register slash commands: /clip, /search, /recent, /stats
  ├─ Set rich presence
  └─ Start auto-start timer (30s delay for GUI restarts)

User: /clip <query>
  │
  ├─ Check role authorization (discord_allowed_roles)
  │
  ├─ Check persistent rate limit
  │
  ├─ Store.list_clips(search=query, limit=5)
  │
  ├─ Build Discord embed:
  │   ├─ Title, game, duration, resolution
  │   ├─ Thumbnail image
  │   ├─ Size (human-readable)
  │   └─ R2 URL (if include_clip_url enabled)
  │
  └─ Send embed to Discord channel

Webhook: New clip uploaded
  │
  ├─ Check notify_on filters
  ├─ Check per_game_filter
  ├─ Check webhook enabled
  ├─ Decrypt webhook URL
  ├─ Build embed (same as /clip)
  ├─ POST to webhook URL
  └─ Log result to webhook_log table
```

## MCP Flow (AI Agent → Tool → Response)

```
MCP Server starts
  │
  ├─ HTTP: POST http://127.0.0.1:8742/tools/{name}
  │   ├─ Authorization: Bearer <token>  (mutations only)
  │   └─ Body: { params: {...} }
  │
  ├─ OR stdio: JSON-RPC on stdin/stdout
  │
  ├─ Tool handler:
  │   ├─ clip_list → Store.list_clips(...)
  │   ├─ clip_get → Store.get_clip(...)
  │   ├─ clip_search → Store.list_clips(search=...)
  │   ├─ stats_get → Store.get_aggregate_stats()
  │   ├─ game_profile_list → Store.list_game_profiles()
  │   ├─ webhook_list → Store.list_webhooks()
  │   ├─ webhook_test → test webhook URL
  │   └─ pipeline_enqueue → Pipeline.enqueue(...)
  │
  └─ Response: JSON { result: ..., error: ... }
```

## Application Startup Flow

```
moment CLI
  │
  ├─ Parse args
  │
  ├─ Dispatcher:
  │   ├─ "bot" → moment.bot.main.run_bot()
  │   ├─ "mcp" → moment.mcp.main.run_mcp()
  │   └─ default → moment.ui.app.main()
  │
  └─ GUI mode:
      │
      ├─ AppManager.__init__()
      │   ├─ Parse args
      │   └─ Init signal/slot infrastructure
      │
      ├─ AppManager.init()
      │   ├─ Create QApplication
      │   ├─ Apply dark stylesheet + font
      │   ├─ Set global exception hook
      │   ├─ _init_services()
      │   │   ├─ Config() → settings table
      │   │   ├─ Store() → encrypted DB
      │   │   ├─ _init_gsr() → GSRController + GSRWatcher + Overlay + Hotkey
      │   │   ├─ _init_pipeline() → Pipeline with GameMonitor
      │   │   └─ Bookmarker()
      │   ├─ Create TrayIcon
      │   ├─ _create_window() → MainWindow with pages
      │   └─ Post-init (--settings flag, etc.)
      │
      └─ AppManager.exec() → QApplication.exec()
```

## Application Shutdown Flow

```
AppManager._on_quit()
  │
  ├─ GSRController.stop()
  ├─ GSRWatcher.stop()
  ├─ GlobalHotkeyManager.unregister()
  ├─ Overlay.hide()
  ├─ GameMonitor.stop()
  ├─ Pipeline.shutdown()
  │   ├─ Set shutdown event
  │   ├─ Wake paused workers
  │   ├─ Push sentinel tasks
  │   └─ Join workers (30s timeout)
  ├─ Store.close()
  └─ QApplication.quit()
```

## Game-Aware Pausing Flow

```
GameMonitor polls /proc for game processes
  │
  ├─ Game detected → on_game_state_changed("GAME_ACTIVE", game_name)
  │   │
  │   ├─ Pipeline.pause()
  │   │   ├─ Set _paused = True
  │   │   └─ Encode + Thumbnail workers block on _pause_lock
  │   │
  │   └─ Upload workers continue (non-GPU work)
  │
  └─ Game exits → on_game_state_changed("IDLE", None)
      │
      ├─ Pipeline.resume()
      │   ├─ Set _paused = False
      │   └─ _pause_lock.notify_all() → workers unblock
      │
      └─ Post-capture action:
          ├─ Review card (show UI)
          ├─ Discard (delete clip)
          └─ Editor (open trim dialog)
```

## Signal Bridge (Worker → UI)

```
Worker thread                UI thread (Qt event loop)
─────────────                ─────────────────────────
Pipeline._process_encode()
  │
  ├─ self._on_clip_encoded(stem)
  │   └─ This is a pyqtSignal.emit() call
  │                           │
  │                           ▼
  │                    AppManager._on_pipeline_clip_encoded()
  │                      │
  │                      └─ Toast: "Clip encoded: {stem}"
  │
  ├─ self._on_clip_uploaded(stem, url)
  │   └─ pyqtSignal.emit()
  │                           │
  │                           ▼
  │                    AppManager._on_pipeline_clip_uploaded()
  │                      │
  │                      └─ Toast: "Clip uploaded → {url}"
  │
  └─ self._on_status(text)
      └─ pyqtSignal.emit()
                          │
                          ▼
                    AppManager._on_pipeline_status()
                      │
                      ├─ MainWindow.set_pipeline_status()
                      └─ TrayIcon.update_status()
```
