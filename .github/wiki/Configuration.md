# Configuration

Moment stores its configuration at `~/.config/moment/config.yaml`. You can edit this file directly or use the Settings dialog.

## Config file

```yaml
# Moment configuration
db_dir: ~/.config/moment
data_dir: ~/.local/share/moment
gsr_output_dir: ~/Videos/Moment
encoded_dir: ~/.local/share/moment/encoded
thumbnail_dir: ~/.local/share/moment/thumbnails
temp_dir: ~/.local/share/moment/temp
log_dir: ~/.local/share/moment

# Upload (rclone)
rclone_remote: r2
rclone_bucket: moment
base_url: ""

# Recording
recording_mode: replay       # replay or manual
gsr_fps: 60
gsr_quality: very_high       # ultra, very_high, high, medium, low
gsr_container: mp4
gsr_audio: default_output
gsr_record_area: screen
gsr_show_cursor: true
replay_duration: 60           # seconds

# Performance
encode_pause_during_game: true
max_concurrent_uploads: 2
thumbnail_lru_size: 250

# Hotkeys
save_clip_hotkey: Ctrl+F12
overlay_hotkey: Alt+Z
```

## Environment variables

Environment variables override config file values and are useful for headless setups or containerized deployments:

| Variable | Default | Description |
|---|---|---|
| `MOMENT_RCLONE_REMOTE` | `r2` | rclone remote name |
| `MOMENT_RCLONE_BUCKET` | `moment` | bucket/container on the remote |
| `MOMENT_BASE_URL` | (none) | public URL prefix for shareable links |
| `MOMENT_BOT_TOKEN` | (none) | Discord bot token |

## Storage locations

All paths in the config are user-configurable. See the [Configurable Paths](Configuration#storage-locations) section in Settings or edit `config.yaml` directly.

| Setting | Default | Purpose |
|---|---|---|
| `db_dir` | `~/.config/moment` | SQLite database (clips, game profiles) |
| `data_dir` | `~/.local/share/moment` | Application data |
| `gsr_output_dir` | `~/Videos/Moment` | GSR recorded clip output |
| `encoded_dir` | `./encoded` | Encoded/transcoded clips |
| `thumbnail_dir` | `./thumbnails` | 320×180 clip previews |
| `temp_dir` | `./temp` | Temporary encode files |
| `log_dir` | `./` | Log files |

## Migration from clip-tray

If you were using the previous version (clip-tray), Moment automatically migrates your data on first run:
- `~/.config/clip-tray/` → `~/.config/moment/`
- `~/.local/share/clip-tray/` → `~/.local/share/moment/`
