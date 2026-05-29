# Keyboard Shortcuts

## Default shortcuts

| Shortcut | Action | Context |
|---|---|---|
| **Ctrl+F12** | Save replay buffer | Global (any app) |
| **Alt+Z** | Open save-replay overlay | Global (any app) |
| **Ctrl+S** | Save current clip | Moment window |
| **Ctrl+Delete** | Delete selected clip | Moment window |
| **Ctrl+E** | Export/share selected clip | Moment window |
| **Ctrl+Period (.)** | Next page | Moment window |
| **Ctrl+Comma (,)** | Previous page | Moment window |
| **Ctrl+,** | Open Settings | Moment window |
| **Escape** | Close overlay / close dialog | Overlay / dialogs |

## Change shortcuts

1. Open **Settings → Keyboard tab**
2. Click a shortcut field
3. Press the new key combination
4. Click **Apply**

## KDE Global Shortcut integration

On KDE Plasma, Moment registers shortcuts via `kglobalaccel` (D-Bus). This means they work even when Moment's window is not focused.

To verify or override in KDE:

1. Open **System Settings → Shortcuts**
2. Search for "Moment"
3. You'll see entries for "Moment: Save Clip" and "Moment: Overlay"
4. Customize as you would any KDE shortcut

## Non-KDE desktops

On GNOME, Sway, or other desktops, global shortcuts fall back to window-focused shortcuts — they only work when the Moment window is active. The **Ctrl+F12** save hotkey and **Alt+Z** overlay still work when Moment is focused.

## Conflict notes

**Alt+Z** is the default hotkey for GPU Screen Recorder's native GTK overlay. Moment intercepts this key *before* GSR sees it (on KDE). To use GSR's native overlay, disable Moment's Alt+Z binding in Settings → Keyboard.

## Future

- Customizable per-action shortcuts
- Gamepad/chorded shortcuts
- Per-game shortcut profiles
