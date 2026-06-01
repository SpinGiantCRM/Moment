# Moment

GPU-accelerated game clip manager for Linux. Capture, edit, and share your gaming moments.

**Status:** Pre-release — private development until v1.0.

## Features

- One-click clip capture via `gpu-screen-recorder`
- Hardware-accelerated encoding (NVENC) with presets
- Auto-upload to any storage provider (Backblaze B2, Cloudflare R2, AWS S3, Google Cloud, Wasabi, Dropbox, self-hosted, and 40+ more via rclone)
- Built-in trim, split, speed, filters, overlays, merge
- GIF export with palette optimization
- Discord webhook integration
- Game-aware: pauses GPU work during gameplay
- Keyboard-first UI in ONLYOFFICE Modern Dark style
- MCP server for AI agent integration

## Installation

### 1. System Dependencies

Required system libraries for Moment's encrypted database:

```bash
# Debian / Ubuntu / Pop!_OS
sudo apt install libsqlcipher-dev ffmpeg

# Arch / Manjaro / EndeavourOS
sudo pacman -S sqlcipher ffmpeg

# Fedora
sudo dnf install libsqlcipher-devel ffmpeg
```

Optional but recommended for full features:

```bash
# GPU screen recorder (capture)
# See: https://git.dec05eba.com/gpu-screen-recorder/about/
# or install from AUR / Flathub

# rclone (cloud upload)
# See: https://rclone.org/install/

# librsvg or ImageMagick (desktop icons — needed for install.sh PNG generation)
sudo apt install librsvg2-bin      # Debian/Ubuntu
sudo pacman -S librsvg             # Arch
```

### 2. Install the Python Package

```bash
# Recommended — isolated install (no venv needed)
pipx install "moment-clips[bot,mcp]"
pipx ensurepath  # adds ~/.local/bin to PATH if not already there

# OR from source (for development):
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
python -m venv .venv && source .venv/bin/activate
pip install -e ".[bot,mcp]"

# OR with pip (system-wide, not isolated):
pip install --user "moment-clips[bot,mcp]"
```

### 3. Desktop Integration (Optional)

Registers the app launcher icon so Moment appears in your application menu:

```bash
# Standalone — works without cloning the repo (pinned to latest release):
curl -fsSL https://raw.githubusercontent.com/SpinGiantCRM/moment/master/install/install.sh | bash

# Or from a local repo clone:
cd moment
./install/install.sh

# Pin to a specific release version:
MOMENT_INSTALL_VERSION=0.2.1 curl -fsSL https://.../install.sh | bash
```

This installs the `.desktop` file, SVG icon, PNG icons at 48/64/128/256px, and
helper scripts (`moment-save-replay`).

### 4. Verify

```bash
moment --help        # Should show usage info
moment diagnose      # Print diagnostic report
```

## Quick Start

```bash
moment                  # Launch GUI
moment import <path>    # Import a video file
moment export <clip_id> # Export a clip
moment diagnose         # Print diagnostic report
moment bot              # Start Discord bot
moment mcp              # Start MCP server for AI agent access
```

### Discord Bot (systemd)

A user systemd service is available for running the Discord bot persistently:

```bash
# From a repo clone
cp install/moment-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now moment-bot.service

# Check status
systemctl --user status moment-bot.service
journalctl --user -u moment-bot.service -f
```

The bot auto-starts when you log in and restarts on failure.

### Arch Linux (AUR)

A `PKGBUILD` is included in the repo. Build and install with:

```bash
makepkg -si
```

## Documentation

- [Getting Started Guide](docs/guides/getting-started.md) — from zero to your first clip
- [AI Agent Briefing](AGENTS.md) — what you need to know before coding
- [Architecture Overview](ARCHITECTURE.md) — system architecture, request flows, thread model
- [Security Model](SECURITY.md) — encryption, credentials, authentication
- [Contributing](CONTRIBUTING.md) — how to contribute
- [Storage Providers](docs/storage-providers.md) — configure rclone for Backblaze B2, Cloudflare R2, AWS S3, and more
- [Database Schema](docs/database/schema.md) — full table reference
- [Truth](TRUTH.md) — complete feature inventory with current and striving states

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright © Chase M. All rights reserved.
