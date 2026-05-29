# FAQ

## General

### What is Moment?

Moment is a GPU-accelerated game clip manager for Linux. It runs GPU Screen Recorder silently in the background with a circular replay buffer, and lets you save clips after the fact with a hotkey — like Shadowplay for Linux.

### How is this different from OBS?

OBS Studio is a full streaming/recording suite. Moment is purpose-built for game clips: always-recording background buffer, instant save, auto-encoding, auto-upload. You wouldn't use OBS to auto-capture your last 60 seconds of gameplay without managing recordings yourself.

### How is this different from GPU Screen Recorder's built-in UI?

GSR ships with a GTK overlay (Alt+Z) for its replay buffer. Moment provides:
- A proper PyQt6 library manager with grid view, search, and stats
- Auto-encoding pipeline with GPU acceleration
- Auto-upload to any cloud storage
- Discord bot integration
- Desktop integration (system tray, global shortcuts)
- Settings management for all GSR parameters

## Recording

### Does it affect game performance?

GSR uses ~2-5% GPU for recording, which is negligible on modern GPUs. The replay buffer doesn't write to disk until you save. Moment's encoder pauses during gameplay (configurable) to avoid competing for GPU cycles.

### How much RAM does the replay buffer use?

~500 MB for 60 seconds at 1080p60. At 4K60, ~1.5 GB. The buffer is circular — it doesn't grow indefinitely.

### Can I record specific windows?

Yes. GSR supports `-w focused` (active window) and `-w portal` (Wayland portal selection). Set this in Settings → Recording → Record area.

### What audio is captured?

By default, all system audio. You can select a specific PulseAudio sink or source in Settings → Recording → Audio input.

## Storage

### Where are clips stored locally?

`~/Videos/Moment/` by default. Configurable in Settings → Storage Locations.

### Where is the database?

`~/.config/moment/clips.db` — SQLite with WAL mode. Contains clip metadata, upload states, game profiles, and settings.

### How do I move my data?

1. Stop Moment
2. Copy the entire `~/.config/moment/` and `~/.local/share/moment/` directories
3. Restart Moment with the new paths configured in Settings

## Cloud uploads

### Do I need cloud storage?

No. Moment works fully offline. Cloud upload is optional.

### Which providers are supported?

40+ via rclone. See [Cloud Storage](Cloud-Storage) for popular options.

### How do I get shareable links?

Set `MOMENT_BASE_URL` (env var) or `base_url` (config.yaml) to your storage provider's public URL prefix.

### Is upload secure?

Yes. rclone encrypts all transfers via HTTPS/SSH. Credentials live in `~/.config/rclone/rclone.conf` (600 permissions).

## Troubleshooting

### Moment won't start

```bash
# Check dependencies
which gpu-screen-recorder
which ffmpeg
which rclone

# Reset config
mv ~/.config/moment ~/.config/moment.bak
moment

# Check logs
cat ~/.local/share/moment/moment.log
```

### Clips aren't being saved

1. Is the save hotkey configured correctly? Check Settings → Keyboard.
2. Is GSR running? Check the tray icon — should show a green ●.
3. Check the output directory exists: `ls ~/Videos/Moment/`
4. Manual save via terminal: `killall -USR1 gpu-screen-recorder`

### Uploads fail

1. Is rclone configured? `rclone listremotes`
2. Check your remote is accessible: `rclone ls remote:bucket`
3. Check logs: `journalctl -f | grep moment`

### The overlay doesn't appear

On KDE: ensure "Moment: Overlay" shortcut is registered in System Settings → Shortcuts.
On other desktops: the overlay only works when the Moment window is focused (for now).

### I found a bug

Report it at [github.com/SpinGiantCRM/Moment/issues](https://github.com/SpinGiantCRM/Moment/issues) with:
- Moment version (`moment --version`)
- Your GPU/driver info
- Steps to reproduce
- The log file at `~/.local/share/moment/moment.log`
