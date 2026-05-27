# Spec: Tray Icon + Desktop Launcher + Autostart

**Date:** 2026-05-27  
**Status:** DRAFT  
**Supersedes:** N/A — augments `docs/plan.md`  
**Related files:** `ui/tray.py`, `ui/resources.py` (new icon), `src/moment/` (package rename)

---

## 1. Naming — "Moment"

Rename the entire project to **"Moment"** (as in capturing gaming moments).

| Scope | Old Name | New Name |
|-------|----------|----------|
| Package name | `clip-tray` | `moment` |
| Binary | `clip-tray` | `moment` |
| Python import | `clip_tray` | `moment` |
| Directory | `src/clip_tray/` | `src/moment/` |
| `.desktop` file | — | `Moment.desktop` |
| Icon file | `clip-tray.svg` | `moment.svg` |
| Config directory | `~/.config/clip-tray/` | `~/.config/moment/` |
| DB path | `~/.config/clip-tray/clips.db` | `~/.config/moment/clips.db` |
| Log path | `~/.local/share/clip-tray.log` | `~/.local/share/moment.log` |
| UI window title | `"Clip Pipeline"` | `"Moment"` |
| Tray tooltip | — | `"Moment"` (+ status) |

### Migration path

Clip-tray → Moment migration is handled at the same cutover as the old script replacement (Phase 2):

1. On first launch, attempt to read old SQLite at `~/.config/clip-tray/clips.db`
2. If found and non-empty, import all clips into `~/.config/moment/clips.db`
3. If old `clips.json` exists (pre-SQLite), run the original JSON → SQLite migration, then rename to `clips.json.bak`
4. Symlink: `~/.local/bin/clip-tray` → `moment` (for backward compatibility during transition)

---

## 2. Tray Icon Design

### 2.1 New SVG Icon

Design a new icon replacing the current clipboard outline. Direction: a stylized "M" or a capture/record icon (circle/dot motif) representing a "moment" capture.

Design constraints:
- **Monoline outline style** matching the UI design system (§4.4 of plan)
- **24×24 grid** for the tray version
- **Scalable** — SVG at `hicolor/scalable/apps/moment.svg` (primary)
- **Multi-resolution** — generate PNGs at 16×16, 22×22, 24×24, 32×32, 48×48, 64×64, 128×128, 256×256 for `hicolor/*/apps/moment.png`
- 78% opacity white for normal state (matching outline icon spec)
- Full white on hover/active
- **Single icon, no state variants** — status conveyed via tooltip text only

### 2.2 Tray Icon States (Visual)

Per the user's preference, use **one consistent icon** for all states. No color changes, no badges, no overlays. Status is communicated through:

1. **Tooltip text** (primary — see §2.4)
2. **Toast notifications** (secondary — see §6 of plan)

### 2.3 Tray Menu

```
─────────────────────
 Moment — Idle        ← Status line (disabled, non-clickable)
─────────────────────
 Open Moment          ← Show/hide main window
─────────────────────
 📹 Save Replay       ← Triggers F8 equivalent
 📸 Screenshot        ← Triggers Ctrl+F8 equivalent
 📌 Bookmark          ← Triggers Ctrl+F9 equivalent
─────────────────────
   3 minutes ago      ← Section header (disabled)
 Replay_2026-05-27…   ← Click → copy URL to clipboard
 Replay_2026-05-26…   ← Click → copy URL to clipboard
─────────────────────
 Settings…            ← Opens Settings dialog
 Quit                 ← Quit application
─────────────────────
```

**Menu behavior rules:**
- **Recent clips section**: Shows the 3 most recently uploaded clips. Visible only if clips exist. Clicking a clip copies its URL to clipboard (quick access while gaming). Each item shows clip title/date, max 40 chars.
- **Dynamic items**: "Save Replay" / "Screenshot" / "Bookmark" are disabled if the daemon/hotkey system isn't running.
- **Status line**: One-line current state (see §2.4). Updated in real-time.
- **Open Moment**: Toggles window visibility (show if hidden, focus if minimized).

### 2.4 Tray Tooltip

Single-line status text, updated by pipeline state changes. Format:

| State | Tooltip Text |
|-------|-------------|
| Idle, no pending work | `"Moment — Idle"` |
| Encoding (single) | `"Moment — Encoding clip-1.mp4"` |
| Uploading (single) | `"Moment — Uploading clip-1.mp4"` |
| Multiple pipeline tasks | `"Moment — 3 clips encoding"` |
| Game active (paused) | `"Moment — Game active (paused)"` |
| Error state | `"Moment — Error: {brief message}"` |
| Upload complete (brief) | `"Moment — Upload complete"` |

### 2.5 Tray Behavior Rules

| Action | Behavior |
|--------|----------|
| **Left-click** | Toggle main window visibility (show/hide) |
| **Left-click (window visible)** | Focus window, raise to top |
| **Double-click** | Same as left-click (no separate behavior) |
| **Right-click** | Open context menu (§2.3) |
| **Middle-click** | Copy last clip URL to clipboard (quick action) |
| **Scroll wheel** | No action (reserved for future: cycle through recent clips) |
| **Close window** | `closeEvent` → hide to tray (never quit on window close) |
| **App quit** | Only via Quit in tray menu, or SIGTERM |

### 2.6 Integration with Toast System

The tray is the **visual anchor** for toasts. When the window is minimized/hidden, toasts serve as the primary notification channel. When the window is visible, toasts still appear but user may also see status in the window's processing banner.

**No toast duplication:** If a toast is shown for an event (e.g., "Upload complete"), the tray tooltip updates to match but does NOT show a separate notification. The toast IS the notification.

---

## 3. Desktop Launcher (.desktop File)

### 3.1 File Location

`~/.local/share/applications/Moment.desktop`

### 3.2 File Content

```ini
[Desktop Entry]
Type=Application
Name=Moment
Comment=Record, encode, and share gaming clips
Exec=moment
Icon=moment
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=true
Actions=Open Encoded Folder;Settings

[Desktop Action Open Encoded Folder]
Name=Open Encoded Folder
Exec=xdg-open ~/Videos/Clips/Encoded

[Desktop Action Settings]
Name=Settings
Exec=moment --settings
```

### 3.3 Desktop Actions

The `Desktop Actions` provide right-click options in the KDE application launcher:

1. **Open Encoded Folder** — opens the directory where MP4s are stored
2. **Settings** — launches Moment directly to the Settings dialog

Future additions: "Open Grid", "Start Capture" if feasible.

### 3.4 Categories Rationale

- `Utility` — primary category (system utility for clip management)
- `AudioVideo` — secondary (handles video encoding/playback)
- NOT `Game` — Moment is a tool that supports gaming, not a game itself

---

## 4. Autostart

### 4.1 File Location

`~/.config/autostart/Moment.desktop`

### 4.2 File Content

A copy of the same .desktop file with additional `X-KDE-autostart-after=plasma-core`:

```ini
[Desktop Entry]
Type=Application
Name=Moment
Exec=moment
Icon=moment
Terminal=false
Categories=Utility;
X-KDE-autostart-after=plasma-core
StartupNotify=false
```

### 4.3 Autostart Behavior

- **Start minimized to tray** — the main window is NOT shown on autostart. Only the tray icon appears.
- **Pipeline starts immediately** — watcher begins monitoring, backlog processing begins.
- **First-launch exception**: On the VERY first launch after migration (no clips in DB), show the window to confirm migration succeeded, then minimize to tray.
- **Config toggle**: Add a "Start on login" checkbox in Settings (General tab) to enable/disable autostart. Implementation: create/remove the `~/.config/autostart/Moment.desktop` file. No need for `systemctl --user`.

### 4.4 How Autostart is Toggled in Settings

The autostart .desktop file is managed programmatically:

```
~/.config/autostart/Moment.desktop   ← Created on "Start on login" enable
                                    ← Deleted on disable
```

Implementation: Simple file write/unlink in `core/config.py` (or autostart helper in `utils/system.py`).

---

## 5. CLI Arguments

The `--minimized` flag controls whether the window is shown on launch. The `.desktop` and autostart files pass this flag.

| Flag | Behavior |
|------|----------|
| *(none)* | Show window normally (default when run from terminal) |
| `--minimized` | Start with tray icon only, no window (used by autostart) |
| `--settings` | Open directly to Settings dialog |
| `--help` | Show usage and exit |

---

## 6. Integration with Existing Plan

### 6.1 New Phase 2.12 (Add after existing Phase 2.11)

| Unit | Deliverable |
|------|------------|
| 2.12 | Full tray spec (menu, tooltip, click behavior, state) |
| 2.13 | `moment.svg` icon (SVG + multi-res PNGs) |
| 2.14 | `Moment.desktop` for application launcher |
| 2.15 | Autostart `Moment.desktop` |
| 2.16 | `--minimized` / `--settings` CLI flags |
| 2.17 | Autostart toggle in Settings dialog |

### 6.2 Phase 2.2 Update

`ui/app.py` (AppManager) needs to:
- Accept `--minimized` flag
- Accept `--settings` flag
- Wire the close-to-tray behavior
- Emit tray state signals

### 6.3 Phase 2.3 Update

`ui/tray.py` needs to implement the full spec defined here.

### 6.4 Agents.md Update

Add the following to agents.md:
- Tray section with menu layout, tooltip behavior
- Mention that `moment` is the new name
- Desktop file paths

---

## 7. Phase Allocation

The new items fit into the existing Phase 2 (GUI Skeleton) structure without adding a new phase:

| Chunk | Phase | Work |
|-------|-------|------|
| **2.12** | Phase 2 | `ui/tray.py` — full tray spec implementation (menu, tooltip, click, state) |
| **2.13** | Phase 2 | Icon design — SVG + multi-res PNGs for `moment.svg` |
| **2.14** | Phase 2 | `Moment.desktop` for application launcher |
| **2.15** | Phase 2 | Autostart file + toggle in Settings |
| **2.16** | Phase 2 | `--minimized` / `--settings` CLI args in `main.py` |

**Note:** Package renaming to "Moment" touches the whole project. Recommend implementing the full Phase 0 (Foundation) first with `clip_tray` as-is, then do the rename as a dedicated pass before Phase 2.

---

## 8. Verification / Acceptance Criteria

1. `moment` command launches the app
2. Tray icon appears in KDE system tray (Wayland)
3. Tooltip updates dynamically with pipeline state
4. Tray menu shows: Status line, Open Moment, Capture controls, Recent clips, Settings, Quit
5. Left-click toggles window visibility
6. `moment --minimized` starts with no window (tray only)
7. Close window → hides to tray (doesn't quit)
8. `Moment` appears in KDE application launcher search (Super key → "Moment")
9. Right-click in launcher shows "Open Encoded Folder" and "Settings" desktop actions
10. "Start on login" toggle creates/removes `~/.config/autostart/Moment.desktop`
11. On login, Moment starts minimized to tray
12. Old `clip-tray.py` still works alongside (backward compat)

---

## 9. Open Questions / Future Considerations

- **KDE Wayland tray limitations**: Qt6 QSystemTrayIcon works on Wayland, but the legacy systray protocol may not. If the icon doesn't appear, fall back to `StatusNotifierItem` via `snoretoast` or the `qt6-wayland` tray backend. Document as "best-effort on Wayland" for initial release.
- **Multiple monitors**: Tray icon appears on the primary monitor's system tray. No special multi-monitor handling needed.
- **App indicator vs system tray**: If KDE moves away from XEmbed system tray, may need to support `StatusNotifierItem` protocol. Monitor Qt6/KDE developments.
- **Autostart timing**: If gpu-screen-recorder starts after Moment, the watcher may miss clips created during boot. This is acceptable — the watcher scans every 10s so it will catch them within one interval.
