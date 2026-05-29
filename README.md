# Moment

GPU-accelerated game clip manager for Linux. Capture, edit, and share your gaming moments.

**Status:** Pre-release — private development until v1.0.

<!-- TODO: Add screenshots and demo GIF at v1.0 -->

## Features

- One-click clip capture via `gpu-screen-recorder`
- Hardware-accelerated encoding (NVENC) with presets
- Auto-upload to any storage provider (Backblaze B2, Cloudflare R2, AWS S3, Google Cloud, Wasabi, Dropbox, self-hosted, and 40+ more via rclone)
- Built-in trim, split, speed, filters, overlays, merge
- GIF export with palette optimization
- Discord webhook integration
- Game-aware: pauses GPU work during gameplay
- Keyboard-first UI in ONLYOFFICE Modern Dark style

## Requirements

- Python 3.11+
- PyQt6
- ffmpeg with NVENC (`h264_nvenc`, `hevc_nvenc` or `av1_nvenc`)
- rclone with a remote configured (see [storage providers](docs/storage-providers.md))
- gpu-screen-recorder *(optional, for capture)*
- NVIDIA GPU *(optional, for NVENC — software fallback available)*

## Installation

```bash
pip install git+https://github.com/SpinGiantCRM/moment.git

# With optional features:
pip install "moment[bot,mcp]"
```

### Arch Linux (AUR)

<!-- TODO: Add AUR package link at v1.0 -->

## Quick Start

```bash
moment                  # Launch GUI
moment --minimized      # Start in tray
moment bot              # Start Discord bot (requires discord.py)
moment mcp              # Start MCP server for AI agent access
```

## Documentation

- [Architecture Overview](docs/plan.md)
- [Storage Providers](docs/storage-providers.md) — configure rclone for Backblaze B2, Cloudflare R2, AWS S3, and more

## Development

```bash
git clone https://github.com/SpinGiantCRM/moment.git
cd moment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[bot,mcp]"
pytest tests/
```

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).

Copyright © Chase M. All rights reserved.
