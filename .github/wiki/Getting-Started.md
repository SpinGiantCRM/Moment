# Getting Started

## Prerequisites

- **Linux** (KDE Plasma recommended; GNOME/Sway supported)
- **Python 3.11+**
- **GPU Screen Recorder** — `gpu-screen-recorder` (install from [AUR](https://aur.archlinux.org/packages/gpu-screen-recorder) or [GitHub releases](https://github.com/dec05eba/gpu-screen-recorder/releases))
- **ffmpeg** with your GPU's encoder (NVENC, VAAPI, or QSV)
- **rclone** — for cloud uploads (optional, but recommended)

### Optional but useful

| Tool | Purpose |
|------|---------|
| `nvidia-smi` | GPU vendor detection for optimal encoder |
| `lspci` | Fallback GPU detection |
| `kglobalaccel` (KDE) | Global hotkey for save-replay overlay |
| `discord.py` | Discord bot integration |

## Installation

### From PyPI

```bash
pip install moment
```

### From AUR (Arch Linux)

```bash
yay -S moment
```

### From source

```bash
git clone https://github.com/SpinGiantCRM/Moment.git
cd Moment
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Desktop integration

After installation, run the install script to add Moment to your app launcher:

```bash
./install/install.sh --user
```

This installs:
- `~/.local/share/applications/moment.desktop`
- Hicolor SVG + PNG icons (48×48 to 256×256)
- `~/.local/bin/save-replay.sh`

## First run

Launch Moment from your app launcher or terminal:

```bash
moment
```

On first launch, Moment:
1. Creates `~/.config/moment/` with default `config.yaml`
2. Creates `~/.local/share/moment/` for thumbnails and temporary data
3. Detects your GPU and selects the best encoder
4. Prompts you to configure cloud storage (optional)
5. Starts the GPU Screen Recorder replay buffer in the background

You'll see the Moment window with an empty clip grid and the tray icon.

## Verify it's working

1. Check the tray icon — it should show a green ● indicator (recording active)
2. Press the save hotkey (**Ctrl+F12** by default) — the overlay appears
3. Tap **Save 30s** — a toast confirms the clip was saved
4. The clip appears in the grid within 2 seconds

## Next steps

- [Configure cloud storage](Cloud-Storage) to auto-upload clips
- [Customize recording settings](Recording) (FPS, quality, codec)
- [Set up keyboard shortcuts](Keyboard-Shortcuts) for your workflow
