# Plan: Moment (prev. clip-tray) — Consolidated Rebuild Plan

**Status:** OPEN
**Created:** 2026-05-27
**Updated:** 2026-05-28 — Reorganized into architecture + micro-specs
**Target:** ~/projects/clip-tray/ → final rename to ~/projects/moment/ (see §2.3)
**Architecture ref:** `.ai_context/architecture.md`
**Micro-specs:** `specs/`

---

## 1. Philosophy

**Be Medal-quality on Linux.** Seamless pipeline from recording to shareable URL. Game performance always prioritized. Keyboard-accessible. Beautiful dark UI inspired by ONLYOFFICE Modern Dark — clean, minimal, flat, generous whitespace, floating island toolbars.

**Capture strategy:** Wrap `gpu-screen-recorder` as a thin subprocess controller. Do NOT reimplement screen capture — the Vulkan/Wayland layer is the hardest, most maintenance-heavy part. Invest in the controller, not the capture engine.

**Design values:** Clean, flat, minimal. No gradients. No unnecessary borders. Generous whitespace. Floating "island" toolbars. Outline icons. Dark but not black — medium charcoal backgrounds with high-contrast text.

---

## 2. App Naming

### 2.1 Direction: "Moment"

The project is renamed to **"Moment"** (as in capturing gaming moments). "Moment" captures the emotional intent — preserving fleeting gaming highlights.

### 2.2 Rename Scope

| Scope | Dev Name | Release Name |
|-------|----------|-------------|
| Package | `clip-tray` | `moment` |
| Binary | `clip-tray` | `moment` |
| Import | `clip_tray` | `moment` |
| Config dir | `~/.config/clip-tray/` | `~/.config/moment/` |
| DB path | `~/.config/clip-tray/clips.db` | `~/.config/moment/clips.db` |

### 2.3 Rename Strategy

**Develop as clip-tray, rename to Moment at Phase 8.** Single atomic commit: rename package, imports, config paths, DB paths, .desktop file, icons. Migration path: old DB → new dir on first Moment launch. Symlink: `clip-tray` → `moment` for backward compat.

---

## 3. Architecture

See `.ai_context/architecture.md` for:

- **Data Model** — Clip, EditProfile, Bookmark, Webhook, GameProfile dataclasses + enums
- **Module Structure** — core/ (pure logic), ui/ (PyQt6), utils/
- **Data Flow** — gpu-screen-recorder → MKV → Watcher → Pipeline → GUI
- **Threading Model** — 6 threads with GPU semaphore
- **Visual Design** — ONLYOFFICE Modern Dark palette (17 color tokens)
- **Key Constraints** — startup <500ms, memory <100MB rest / <200MB encode, toast rules, hard-error modals

---

## 4. Implementation Phases

| Phase | Name | Spec | Description |
|-------|------|------|-------------|
| 0 | Foundation | `00-foundation.md` | Package scaffold, utils, models, store, config, logging |
| 1 | Core Pipeline | `02-pipeline.md` | Task queue, encoder (NVENC), uploader (R2), watcher, thumbnail, corruption, retention |
| 2a | GUI Skeleton | `04-ui-tray.md`, `05-ui-window.md`, `06-ui-widgets.md` | App, tray, main window, grid, player, settings, hover preview, toast |
| 2b | Review Cards + Editor | `06-ui-widgets.md`, `07-advanced.md` | Clip Review Card, game profiles, game exit flow, trim dialog, editor view, stats, batch ops |
| 2c | Widgets + Polish | `06-ui-widgets.md` | Skeleton cards, progress ring, processing banner, desktop file, SVG icons, empty states |
| 3 | Capture Controller | `03-capture.md` | Recorder controller, hotkey daemon, bookmarker, screenshot, noise suppression |
| 4 | PiP + Discord + Trash | `07-advanced.md` | PiP window, Discord webhook, trash page, import/export |
| 5 | Editing Enhancements | `07-advanced.md` | Timeline editor, audio mixer, filters, overlays, chroma key, merge, Ken Burns, crop, music, GIF |
| 8 | Rename to Moment | `10-deployment.md` | Atomic rename of package, config paths, DB. Old DB migration. |

---

## 5. Testing

See `08-validation.md` for full testing spec.

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | `pytest` | Models, store, config, encoder/uploader commands, corruption, retention |
| Integration | Manual + pytest | Full pipeline, game detection, trim flow, migration |
| UI | Manual | Window, toasts, tray, keyboard shortcuts, visual correctness |

---

## 6. Risks

| Risk | Mitigation |
|------|-----------|
| QMediaPlayer Linux spotty | H264 tested OK. HEVC transcode to H264. PiP uses QPixmap frames, not QVideoWidget. |
| PiP conflicts with fullscreen GL | Frame-by-frame QPixmap, not QVideoWidget. |
| Wayland global hotkeys limited | KDE D-Bus API; XWayland fallback. "Best-effort on Wayland" for initial release. |
| Wayland QSystemTrayIcon may not appear | Fall back to StatusNotifierItem. |
| gpu-screen-recorder SIGRTMIN unreliable | Manual bookmark fallback. |
| GPU contention during encode | Single-thread semaphore. Encode paused during game. RTX 4080 NVENC is fast. |
| Migration failure | `clips.json` renamed to `.bak`, never deleted. Full rollback possible. |

---

## 7. Remaining Gaps

| Gap | Impact | Resolution |
|-----|--------|------------|
| Rclone remote configuration UI | Medium | Manual config for now. Future: wizard. |
| Keyboard shortcut config UI | Medium | Implement as dialog in Phase 3. |
| First-run wizard | Low | Empty state guide card is sufficient. |
| Sound notifications | Low | QSoundEffect + .wav files. Add in Phase 2c. |
| Trash auto-purge | Low | Revisit when trash page is implemented. |
| No audio routing flags detail | Medium | Research during Phase 3. |

---

## 8. Next Steps

1. Begin Phase 0: Foundation — `specs/spec-seven.md` (backend core)
2. Iterate through phases in order
3. At Phase 2a completion: cutover from old script (`rm ~/.local/bin/clip-tray.py`)
4. Phase 8: rename to Moment
