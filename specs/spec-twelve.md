# spec-twelve: About Dialog

`ui/dialogs/about_dialog.py` — accessible from Help menu in toolbar, tray menu, and `?` key.

---

## Layout

Three-tab `QTabWidget` inside a `QDialog`:
- Tab 1: **Keyboard Shortcuts**
- Tab 2: **License**
- Tab 3: **Credits**

Window: 520x420, centered on parent. Title: "About Moment".

---

## Tab 1: Keyboard Shortcuts

Two-column table (`QTableWidget`, read-only, no grid lines):
| Shortcut | Action |
|----------|--------|
| F8 | Save 30s replay |
| F9 | Save 60s replay |
| F10 | Save 5min replay |
| Ctrl+F8 | Take screenshot |
| Ctrl+F9 | Bookmark |
| Space / K | Play / Pause |
| Left / Right | -5s / +5s seek |
| Up / Down | Volume +10% / -10% |
| F | Toggle fullscreen |
| Esc | Back / Exit fullscreen |
| I | Mark trim in-point |
| O | Mark trim out-point |
| P | Preview trim |
| S | Split at playhead (editor) |
| Del | Delete selected clip |
| F2 | Rename clip |
| Ctrl+C | Copy URL |
| ? | Open this dialog |

Rows sorted by category: Capture, Playback, Trim/Edit, General. Categories separated by alternating row shade.

## Tab 2: License

`QTextBrowser` with `QPlainTextEdit`-like appearance (read-only, no scrollbar from the browser itself — let the tab scroll).

Shows:
```
Moment — GPU-accelerated game clip manager
Copyright © Chase M.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

[full GPL-3.0 text follows]
```

Bottom link: "View full license at gnu.org/licenses/gpl-3.0.txt" (opens browser via `QDesktopServices::openUrl`).

## Tab 3: Credits

List of libraries used, with Python package name, purpose, and license.

Format: group + rows.

**Core:**
| Library | Purpose | License |
|---------|---------|---------|
| Python 3.11+ | Runtime | PSF |
| PyQt6 | GUI framework | GPL-3.0 |
| ffmpeg | Media encoding | LGPL/GPL |
| rclone | Cloud upload | MIT |
| gpu-screen-recorder | Screen capture | MIT |

**Python packages (runtime):**
| twitch-python (or similar) | [as needed] | [license] |
| discord.py (optional) | Discord bot | MIT |

**Development:**
| pytest | Test framework | MIT |
| ruff | Linter | MIT |

Rows as a `QTableWidget` with alternating shades. Read-only.
