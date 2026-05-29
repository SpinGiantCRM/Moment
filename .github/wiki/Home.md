# Moment

GPU-accelerated game clip manager for Linux. Capture, edit, and share your gaming moments.

![](.github/wiki/assets/moment-banner.png)

## Features

- **Always-recording buffer** — GPU Screen Recorder runs silently in the background with a circular buffer. When you do something cool, save the last N seconds with a keystroke.
- **GPU-accelerated encoding** — Transcode instantly using NVENC (NVIDIA), VAAPI (AMD), QSV (Intel), or software fallback.
- **No vendor lock-in** — Upload to any of 40+ storage providers via rclone: Backblaze B2, Cloudflare R2, AWS S3, Google Cloud, Wasabi, Dropbox, or your own NAS.
- **Discord integration** — Optional bot for sharing clips from any server.
- **Beautiful KDE-native UI** — PyQt6 with dark theme, floating toolbars, and KDE global shortcut support.

## Quick start

```bash
pip install moment
moment
```

See [Getting Started] for setup, prerequisites, and first-run walkthrough.

## Project structure

```
moment/
├── src/moment/
│   ├── core/       # Business logic — store, encoder, uploader, GSR
│   ├── ui/         # PyQt6 — pages, dialogs, widgets, overlay
│   └── utils/      # ffmpeg, system helpers, logging
├── install/        # Desktop entry, save-replay script
├── docs/           # Storage providers guide
└── .github/wiki/   # This wiki
```

## Download

- **Arch Linux (AUR):** `yay -S moment`
- **PyPI:** `pip install moment`
- **GitHub:** [SpinGiantCRM/Moment](https://github.com/SpinGiantCRM/Moment)
