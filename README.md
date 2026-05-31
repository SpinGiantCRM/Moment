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

## Requirements

- Python 3.11+
- PyQt6
- ffmpeg with NVENC (`h264_nvenc`, `hevc_nvenc` or `av1_nvenc`)
- rclone with a remote configured (see [storage providers](docs/storage-providers.md))
- `sqlcipher` system library (for sqlcipher3)
- `gpu-screen-recorder` for capture
- NVIDIA GPU for NVENC (software fallback via libx264 available)

## Installation

### From Source (dev)

```bash
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[bot,mcp]"
```

### From PyPI (user)

```bash
pip install "moment[bot,mcp]"
```

### With pipx (isolated, recommended for users)

```bash
pipx install "moment[bot,mcp]"
```

**Note:** On newer distros (Arch, Fedora 38+) you may need `--break-system-packages` or `PIP_REQUIRE_VIRTUALENV=false` when using pip outside a venv. Prefer pipx in that case.

### Desktop Integration

After installation, register the app icon and desktop entry:

```bash
# Installs desktop file + SVG + PNG icons (48/64/128/256px)
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
./install/install.sh             # user-local install
# Or: sudo ./install/install.sh --system
```

### Arch Linux (AUR)

A PKGBUILD is available in the repository. Submit to AUR at v1.0.

## Quick Start

```bash
moment                  # Launch GUI
moment --minimized      # Start in tray
moment --settings       # Open settings dialog
moment --open-encoded   # Open encoded clips folder
moment bot              # Start Discord bot
moment mcp              # Start MCP server for AI agent access
```

## Documentation

- [AI Agent Briefing](AGENTS.md) — what you need to know before coding
- [Architecture Overview](ARCHITECTURE.md) — system architecture, request flows, thread model
- [Security Model](SECURITY.md) — encryption, credentials, authentication
- [Contributing](CONTRIBUTING.md) — how to contribute
- [Getting Started](docs/guides/getting-started.md) — quick start guide
- [Storage Providers](docs/storage-providers.md) — configure rclone for Backblaze B2, Cloudflare R2, AWS S3, and more
- [Database Schema](docs/database/schema.md) — full table reference
- [Request Flows](docs/architecture/request-flow.md) — detailed request flow diagrams
- [Truth](TRUTH.md) — complete feature inventory with current and striving states

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright © Chase M. All rights reserved.
