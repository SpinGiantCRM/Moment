# clip-tray

GPU-accelerated clip management pipeline for Linux. Records, encodes (NVENC),
uploads to Cloudflare R2, and provides a beautiful dark-themed PyQt6 GUI.

## Quick Start

```bash
pip install -e ~/projects/clip-tray
# Symlink is automatically created by pyproject.toml entry point
clip-tray
```

## Requirements

- Python >= 3.11
- PyQt6
- ffmpeg with NVENC support
- rclone configured with an R2 remote
- gpu-screen-recorder (for capture)
- NVIDIA GPU (for hardware encoding)

## Structure

```
src/clip_tray/
├── __main__.py    # Entry point
├── main.py        # QApplication bootstrap
├── core/          # Business logic (no GUI imports)
├── ui/            # PyQt6 GUI
│   ├── pages/     # Full-page views (grid, player, stats, etc.)
│   ├── dialogs/   # Modal dialogs
│   └── widgets/   # Reusable widgets
└── utils/         # Helpers (ffmpeg, system)
```

## License

MIT
