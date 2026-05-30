# Getting Started with Moment

## Installation

### From Source

```bash
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[bot,mcp]"
```

### With the Install Script

```bash
cd moment
./install/install.sh          # User-local install
./install/install.sh --system # System-wide (requires sudo)
```

### Arch Linux (AUR)

*Coming soon.*

## Quick Start

### Launch the GUI

```bash
moment                    # Full GUI
moment --minimized        # Start in system tray only
moment --settings         # Open settings on launch
```

### First-Time Setup

1. **Start Moment** — it will create `~/.config/moment/clips.db` (encrypted SQLite)
2. **Open Settings** (F10 or tray menu) to configure:
   - **Recording:** Enable GSR replay, set duration, quality, FPS
   - **Upload:** Set rclone remote and bucket
   - **General:** Toggle autostart, minimize-to-tray

### Record Your First Clip

1. **Enable instant replay** in Settings → Recording
2. **Press Alt+Z** to open the overlay
3. **F8** saves a 30-second replay, **F9** saves 60 seconds
4. The clip appears in the Grid page after encoding completes

### View Your Clips

- **Grid:** Browse all clips with search and filters
- **Player:** Click a clip to play, trim, favorite, or share
- **Stats:** See aggregate statistics and per-game breakdown
- **Trash:** Recover or permanently delete soft-deleted clips

## Configuration

### Hotkeys

| Hotkey | Action |
|--------|--------|
| Alt+Z | Show/hide overlay |
| F8 | Save 30s replay |
| F9 | Save 60s replay |
| Ctrl+B | Batch select mode |
| Escape | Back to grid |

### Storage

Moment uses rclone for cloud upload. Configure a remote:

```bash
rclone config             # Set up your cloud provider
rclone config show        # Verify configuration
```

Then configure in Moment Settings → Upload:
- **Remote name:** e.g., `r2`, `b2`, `s3`
- **Bucket/path:** e.g., `moment/clips`

### Discord Bot

```bash
keyring set moment discord_bot_token   # Store your bot token
moment bot                              # Start the bot
```

### MCP Server (AI Agent Access)

```bash
moment mcp                          # stdio mode
moment mcp --http                   # HTTP on 127.0.0.1:8742
moment mcp --http --port 9000 --api-token "secret"  # Auth enabled
```

## Directory Layout

| Path | Purpose |
|------|---------|
| `~/.config/moment/` | Config and database |
| `~/.config/moment/clips.db` | Encrypted SQLite database |
| `~/.local/share/moment/` | Application data |
| `~/.local/share/moment/encoded/` | Encoded MP4 files |
| `~/.local/share/moment/thumbnails/` | Thumbnail JPEGs |
| `~/Videos/Moment/` | Raw GSR recordings |

## Troubleshooting

### "pysqlcipher3 not found"

```bash
# Install system dependencies
sudo apt install libsqlcipher-dev   # Debian/Ubuntu
sudo pacman -S sqlcipher            # Arch

# Reinstall moment
pip install --force-reinstall pysqlcipher3
```

### "Database could not be opened"

```bash
# Check file exists and has correct permissions
ls -la ~/.config/moment/clips.db
# If it's plaintext SQLite, delete and restart:
rm ~/.config/moment/clips.db
moment
```

### "No video encoder available"

```bash
# Check available NVENC encoders
ffmpeg -encoders | grep nvenc
# Fallback to software encoding
ffmpeg -encoders | grep libx264
```

## See Also

- `AGENTS.md` — AI agent briefing
- `ARCHITECTURE.md` — System architecture
- `docs/storage-providers.md` — Cloud storage configuration
- `CONTRIBUTING.md` — How to contribute
