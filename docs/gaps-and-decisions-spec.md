# Spec: Gaps & Architectural Decisions

**Date:** 2026-05-28
**Status:** FINAL — all decisions confirmed via user interview (3+ rounds)
**Supersedes:** N/A — augments `docs/plan.md`
**Related files:** `docs/plan.md`, `docs/fleshed-out-spec.md`, `docs/tray-launcher-spec.md`

---

## 1. YouTube Permanent Clip Storage

### 1.1 Architecture: Plugin/Provider Pattern

Rather than building YouTube-specific integration, Moment uses a **plug-in architecture** where users configure their own storage backend. YouTube is one provider option.

```python
# Storage provider interface (core/storage_providers.py)
@dataclass
class StorageProvider:
    name: str                           # "youtube", "r2", "b2", etc.
    type: Literal["cloud", "youtube", "local", "self_hosted"]
    enabled: bool
    config: dict                        # Provider-specific settings

    # Spillover: when primary provider is full, use next
    order: int = 0

# Storage configuration in settings:
providers:
  - type: youtube
    config:
      credentials_file: ~/.config/moment/youtube-oauth.json
      upload_interval: daily              # daily, hourly, manual
      priority: oldest_first              # oldest clips uploaded first
  - type: r2
    config:
      remote: r2
      bucket: clips
      limit_gb: 8
```

### 1.2 YouTube-Specific

- **OAuth login required** — user authenticates with their Google account
- **Upload queue:** clips are queued and uploaded in order (oldest first unless user marks priority)
- **Priority clips:** user can mark individual clips as "high priority" to skip the queue
- **Upload interval:** daily batch upload (configurable), not per-clip (respects YouTube quota limits of ~6 uploads/day)
- **Visibility:** uploaded as unlisted by default
- **Auto-delete after upload:** optional — remove source after successful YouTube upload (YouTube becomes the permanent archive)

### 1.3 Quota Handling

- YouTube Data API v3: ~10,000 units/day (1 upload ≈ 1,600 units = ~6 uploads/day)
- Moment uses a **quota budget** — tracks remaining quota, pauses uploads when low
- Warning toast when within 20% of daily quota

---

## 2. Making the App Public

### 2.1 Commercial Quality, Free

Moment will be **commercial-quality software distributed for free**. No paid tiers, no subscriptions, no service fees. The app is the product — no cloud service, infrastructure, or ongoing operational costs are provided by you. Users provide their own storage backends (R2, B2, Bunny, YouTube, etc.).

### 2.2 Privacy Stripping

Before public release, all traces of personal information must be removed or made configurable:

| Scope | What to Remove / Generalize |
|-------|---------------------------|
| **Hardcoded paths** | `~/Videos/` → configurable default. No references to specific system layouts. |
| **Config paths** | `~/.config/moment/` is standard. No personal absolute paths. |
| **Default storage** | R2 remote name `r2` → user-configurable. Default remote name: `moment-storage`. |
| **Game process list** | Empty on first launch. User adds their own games. |
| **Logs** | No user-identifiable info (IPs, system usernames, hardware serials). |
| **Clip metadata** | No geolocation, device ID, or hardware fingerprinting. |
| **First-run flow** | Config wizard on first launch — user sets storage, game detection, encoding preferences. |
| **Default R2 config** | Removed. User must add their own `rclone remote`. Guide provided in docs. |

### 2.3 Tutorial / Onboarding

First-run flow (replaces empty grid state for new users with no clips):

```
┌─────────────────────────────────────────────────────────┐
│  Welcome to Moment!                                       │
│                                                           │
│  Moment records gaming clips so you can edit, share,      │
│  and save your best moments.                              │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  1. Set up storage                     [→]       │   │
│  │     Connect R2, B2, or local folder               │   │
│  │                                                    │   │
│  │  2. Add your games                    [→]        │   │
│  │     Tell Moment which games to detect             │   │
│  │                                                    │   │
│  │  3. Configure hotkeys                  [→]        │   │
│  │     F8 = save replay, F9 = bookmark               │   │
│  │                                                    │   │
│  │  4. Ready to capture!                 [Start]     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                           │
│  [Skip]                                          [Next]  │
└─────────────────────────────────────────────────────────┘
```

**Persistent guide card:** Even after onboarding, a dismissible card on the grid page explains basic usage: "Press F8 in-game to save a replay. Press Ctrl+F8 for screenshot."

### 2.4 Documentation Requirements

For public release:
- `README.md` with install instructions (pip, dependencies: ffmpeg, rclone, gpu-screen-recorder, Python 3.11+)
- `docs/setup-guide.md` — storage provider setup (R2, B2, Bunny, YouTube), game profile setup, hotkey configuration
- `docs/faq.md` — common issues: Wayland tray, NVENC availability, audio sources
- `docs/architecture.md` — how the pipeline works, for contributors
- `CONTRIBUTING.md` — how to contribute code, report bugs, request features

### 2.5 Licensing

The app will be distributed under **GPLv3** (because it invokes GPL dependencies like `gpu-screen-recorder` as subprocesses, and the audio shim extends GPL-licensed code). This means:
- Users can freely use, modify, and redistribute the code
- Any distributed modifications must also be GPLv3
- Commercial use is allowed with these terms
- A `LICENSE` file will be bundled with the app (generated at Phase 8)
- An "About Moment" dialog will show version + license info and link to the GitHub repository

---

## 3. Auto-Tagging & Game Detection

### 3.1 Smart Per-Game + Event Detection

- **Primary:** Auto-tag with game name when game is detected (per-game profile: `auto_tag: bool`)
- **Secondary:** Tag suggestion based on:
  - Clip duration (short clips = "highlight", long = "session")
  - Time of day (not applicable for gaming, skip)
  - File size / FPS / resolution (flag if unusual)
- **User-defined auto-tags in game profiles:** optional additional tags added automatically to all clips from that game

### 3.2 Implementation

```python
# In pipeline.py, after Clip is discovered:
# 1. If game is active, set clip.game = detected_game
# 2. If game profile has auto_tag=True:
#    - Add game name as tag
#    - Add any user-defined auto-tags from profile
#    - Run heuristics:
#      if clip.duration < 30: suggest "quick"
#      if clip.fps > 100 and game is competitive: suggest "high-fps"
# 3. Store suggested tags but don't force — user can override
```

### 3.3 Medal-Style Event Detection (Future)

In-game event detection (auto-detect kills/wins without hotkey) is **deferred**. This requires:
- Game-specific plugins or screen analysis (too complex for v1)
- Integration with game APIs (e.g., Counter-Strike GSI)
- Not in scope for initial release

---

## 4. Multi-Channel Audio Recording

### 4.1 Problem

gpu-screen-recorder (GSR) does NOT support multi-track audio recording natively. It captures audio as a single mixed track. We need **separate tracks** for game, mic, and Discord for proper post-processing.

### 4.2 Solution: GSR Audio Shim

Write a thin open-source **shim/extension** to GSR that:

1. Captures audio from multiple PulseAudio/PipeWire sources simultaneously
2. Encodes them as separate audio tracks in the MKV container
3. Sends them alongside the GSR video stream

```python
# High-level approach:
# GSR captures: video + mixed audio (as usual)
# Shim captures via Parec/PW-Dump:
#   - Source 1: game audio (monitor of game's sink)
#   - Source 2: mic audio (default input source)
#   - Source 3: Discord audio (Discord's PulseAudio sink)
# Muxes all tracks into output MKV:
#   ffmpeg -i video_from_gsr -i track_game.wav -i track_mic.wav -i track_discord.wav
#          -map 0:v -map 1:a -map 2:a -map 3:a -c copy output.mkv
```

**Legal:** GSR is open-source (license TBD — check during implementation). A GPL-compatible shim contributing multi-channel audio support upstream is legally fine.

**Scope:** NVIDIA only for v1 (matching GSR's primary target). AMD/Intel VAAPI support deferred.

### 4.3 Audio Tracks

| Track | Source | Volume Slider | Mute Toggle | Noise Suppression |
|-------|--------|---------------|-------------|-------------------|
| Game | Game's audio output (PulseAudio monitor) | 0–200% | ✓ | No (game audio is source material) |
| Mic | Default input device | 0–200% | ✓ | ✓ (RNNoise) |
| Discord | Discord's PulseAudio sink | 0–200% | ✓ | No |

### 4.4 Audio Source Detection

- **Game audio:** Auto-detect from the game process's PulseAudio sink
- **Mic:** Default PulseAudio input source
- **Discord:** Look for Discord's sink in PulseAudio source list (common names: `discord`, `discord-*.monitor`)

### 4.5 Audio Capture Error Handling

| Scenario | Behavior |
|----------|----------|
| Discord not running (no Discord sink) | Skip Discord track. Capture game + mic only. Log warning. |
| Default mic changes mid-session (USB unplug) | Restart audio capture on next clip. Current clip keeps prior mic source. Log warning. |
| PulseAudio → PipeWire (system audio backend change) | Detect which backend is active (`pactl info`). Use `parec` for PulseAudio, `pw-record` for PipeWire. Fallback: skip audio capture entirely. |
| Audio-video sync drift | Both GSR video and audio shim use the same system clock. FFmpeg mux handles sync. Max expected drift: <500ms over a 30-minute session. No special handling needed. |
| Parec/Pw-record not found | Toast warning: "Audio capture unavailable — install pulseaudio-utils or pipewire." Capture video only (no audio tracks). |
| GSR audio shim crash during capture | Current clip saved without multi-track audio (fall back to GSR's built-in mixed audio). Toast: "Audio shim failed — clip may have mixed audio."

### 4.5 Architecture

```
Game audio ──┐
Mic audio ───┼── Parec (parallel capture) ──┐
Discord ─────┘                                │├── ffmpeg mux ──▶ Multi-track MKV

GSR video ────────────────────────────────────┘

### 4.6 GSR Shim Error Handling Summary

The audio shim is **optional but additive**. If it fails at any point, clips are still captured successfully:
- **No shim:** GSR video + mixed audio (current behavior). Clip is usable but audio tracks are mixed.
- **Shim partial (game + mic only):** Two clean tracks. Discord audio is mixed into game track.
- **Shim full (game + mic + Discord):** Three separate tracks. Full post-processing flexibility.
```

---

## 5. Screen Recorder Decision

### 5.1 Do NOT Build From Scratch

**Verdict:** Building a screen recorder from scratch is not feasible for a single developer. gpu-screen-recorder took dedicated developers years to perfect Vulkan/Wayland capture. The Wayland + Vulkan + PipeWire layer is the hardest, most maintenance-heavy part.

**Approach:** Continue wrapping `gpu-screen-recorder` as subprocess. Write a thin audio shim for multi-channel support (see §4).

### 5.2 Why GSR Wins

| Criterion | GSR | OBS | wf-recorder | Custom |
|-----------|-----|-----|-------------|--------|
| Performance | Best | Good | Good | Years of work |
| Wayland support | Native (portal) | Via PipeWire | wlroots only | Years of work |
| Replay buffer | Built-in | Via plugin | No | Years of work |
| Multi-track audio | No | Yes (via audio shim) | No | N/A |
| License | Open | GPLv2 | MIT | Your code |
| Complexity to integrate | Low (subprocess) | Medium (websocket) | Low (subprocess) | Extreme |

### 5.3 Non-NVIDIA Users (Deferred)

AMD and Intel Arc users are **deferred to post-v1**. GSR supports VAAPI for AMD/Intel, but the audio shim will be built and tested on NVIDIA first. When AMD support is added:
- Verify GSR works with `--vaapi` flag on AMD GPUs
- Test the audio shim with AMD's PulseAudio/PipeWire setup (same audio capture code, different video)
- Document AMD/Intel setup in setup guide

### 5.4 Optional: OBS Websocket Support (Future)

For users who already use OBS Studio, add optional backend support via `obs-websocket-py`:
- Moment controls OBS start/stop/save-replay
- OBS provides multi-track audio natively
- No GSR shim needed when using OBS backend
- Deferred to post-v1

---

## 6. Editing Scope — The Essential 8

### 6.1 Features to Keep

| # | Feature | Implementation | Priority |
|---|---------|---------------|----------|
| 1 | **Trim** | Dual-handle timeline (in/out points) | P0 — MVP |
| 2 | **Split** | Split at playhead, create segment | P0 — MVP |
| 3 | **Speed** | Per-segment multiplier 0.1x–4x | P0 — MVP |
| 4 | **Audio Mix** | Game volume, mic volume, mute per track | P0 — MVP |
| 5 | **Filters** | Brightness, contrast, saturation, hue | P1 — Phase 2b |
| 6 | **Crop/Rotate** | Crop overlay on preview, rotate 0/90/180/270 | P1 — Phase 2b |
| 7 | **Music/Soundtrack** | Add background audio file, volume, fade in/out | P2 — Phase 5 |
| 8 | **Overlays** | Text overlay (font, size, position), Image overlay (PNG) | P2 — Phase 5 |

### 6.2 Features Removed from Spec

| Feature | Reason |
|---------|--------|
| **Chroma key** | Too niche for clip editing. Green screen is for streaming, not highlights. |
| **Merge** | Excessive for short clips. User can play clips sequentially. |
| **Ken Burns** | Over-engineered for gaming clips. Auto-zoom is distracting. |
| **GIF export** | GIFs are ancient. WebM/MP4 is standard for sharing. Remove. |

### 6.3 Phase Allocation (Updated)

The 8 essential features are spread across phases:

- **Phase 2b** (alongside editor view): Trim, Split, Speed, Audio Mix
- **Phase 2c/3**: Filters, Crop/Rotate
- **Phase 5**: Music, Overlays

---

## 7. Medal Feature Parity

### 7.1 Features We Match

| Medal Feature | Moment Equivalent | Status |
|--------------|-------------------|--------|
| Hotkey clipping (F8) | GSR + HotkeyDaemon | Planned (Phase 3) |
| Per-game profiles | GameProfile dialog | Planned (Phase 2b) |
| Automatic upload | Pipeline uploader | Planned (Phase 1) |
| Shareable links | R2 URL + clipboard | Planned (Phase 2a) |
| Clip library with grid | GridPage + ClipDelegate | Planned (Phase 2a) |
| Video player + seek | PlayerPage + QVideoWidget | Planned (Phase 2a) |
| Trim editor | TrimDialog | Planned (Phase 2b) |
| Tags + favorites | Tag system + favorite toggle | Planned (Phase 2a) |
| Multi-track audio | GSR audio shim (game + mic + Discord) | New — planned (Phase 3) |

### 7.2 Features We Do NOT Match (v1)

| Medal Feature | Rationale |
|--------------|-----------|
| **Social feed / community** | Not building a social platform. No user accounts, no feed. |
| **Webcam overlay** | Niche for clip editing. Deferred to post-v1. |
| **Auto highlight detection** | Medal's auto-detection (kills, wins) is game-specific and complex. Deferred indefinitely. |
| **Streaks / gamification** | Moment is a utility, not a social app. No streaks, no engagement metrics. |
| **Mobile/Web sync** | Desktop-only for v1. Cloud storage URLs work on any device. |

### 7.3 Medal Feature Integrated: In-Game Overlay (Toast System)

Medal shows brief in-game notifications (clip saved, screenshot taken, low disk space) as a non-intrusive overlay. Moment's **Toast system** serves this purpose:

- Toasts already appear bottom-right, slide-in animation, auto-dismiss
- When a game is active, toasts use `WA_ShowWithoutActivating` (no focus steal)
- Tray tooltip updates for persistent state (encoding, uploading)
- **No Medal-style persistent overlay** (always-on-screen HUD) — per user preference

---

## 8. Link Sharing System

### 8.1 Current System

Auto-upload → URL copied to clipboard. Simple, works. No changes needed for v1.

### 8.2 Extensibility

The sharing system uses a **pluggable URL handler** interface for future additions:

```python
# core/url_handler.py
class UrlHandler:
    """Base for sharing link generation."""
    def generate(self, clip: Clip) -> str: ...
    def shorten(self, url: str) -> str: ...  # Optional

# Current implementation:
class R2UrlHandler(UrlHandler):
    def generate(self, clip: Clip) -> str:
        return clip.r2_url or ""

# Future additions (all confirmed by user):
# - WebGalleryHandler: generates link to a web page with clip preview
# - EmbedHandler: generates embed HTML for Discord/forums
# - ExpiringUrlHandler: generates time-limited signed URLs
# - BatchHandler: generates a playlist linking multiple clips
```

### 8.3 Future Link Features (All Wanted)

| Feature | Description | Target |
|---------|-------------|--------|
| **Web gallery page** | Simple public HTML page listing clips with preview thumbnails | Post-v1 |
| **View tracking** | Track clip views via image pixel or redirect | Post-v1 |
| **Embed player** | HTML5 video embed code for Discord, forums, personal sites | Post-v1 |
| **Batch link generation** | One link → playlist of multiple clips (e.g., a whole session) | Post-v1 |
| **Auto-expiring links** | Links expire after N hours/days. Clock starts on first view. | Post-v1 |

---

## 9. Cloud Storage Options

### 9.1 Multi-Backend Support

Moment supports **multiple storage backends** as interchangeable rclone remotes. User picks in Settings:

| Backend | Storage Cost | Egress Cost | Free Tier | Notes |
|---------|-------------|-------------|-----------|-------|
| **Cloudflare R2** | $0.015/GB/mo | $0 (to Cloudflare) | 10GB storage, 1M operations A/mo | Current. User uses free tier. |
| **Backblaze B2** | $0.006/GB/mo | $0.01/GB | 10GB free | Cheapest storage. Egress costs. |
| **Bunny.net** | $0.01/GB/mo | $0.005/GB | 10GB free + 500GB egress | Best for sharing. Built-in CDN. Low egress. |
| **Wasabi** | $0.006/GB/mo | $0 (no egress) | None | Hot storage. No egress fees. 90-day min. |
| **Self-hosted** | Your hardware | Your network | Unlimited | S3-compatible (MinIO) or raw file copy |

### 9.2 Implementation

- **rclone** is already the upload backend
- Backend switching = changing the rclone remote name + bucket path
- UI: Settings → Storage → ["Cloudflare R2" | "Backblaze B2" | "Bunny.net" | "Wasabi" | "Self-hosted"]
- Each option shows a setup guide in the UI (inline help text)
- User can also set up their own rclone remote manually and select it from a dropdown

### 9.3 Storage Provider Interface (Expanded)

```python
# In settings dialog (Storage tab):
class StorageProvider:
    name: str
    type: Literal["r2", "b2", "bunny", "wasabi", "s3_compatible", "self_hosted"]
    rclone_remote_name: str
    bucket: str                  # Container/folder name
    directory: str = ""          # Optional subdirectory
    max_size_gb: int             # Retention limit (0 = unlimited)
    priority: int = 0            # Fallback order for spillover
```

### 9.4 Spillover Chain

When a provider reaches its size limit, clips spill to the next provider in priority order:

```
R2 (8GB) → B2 (unlimited) → Self-Hosted (local NAS)
```

Configurable in Settings → Storage → "When full: [spill to next provider | stop uploading]"

---

## 10. Branding: The "Moment" Identity

### 10.1 App Name

**Moment** — capturing gaming moments. Short, memorable, one syllable.

### 10.2 Icon: Minimalist "M"

Direction: A stylized, minimalist **"M"** in the outline/monoline style matching the UI design system.

**Design constraints:**
- Monoline outline — ~1.5-2px stroke width
- 24×24 grid for tray, scalable SVG for launcher
- 78% opacity white at rest, full white on hover
- Dark background transparent (works on any tray background)
- Colors: single-color white (no gradients, no fills)
- Aspect: slightly wider than tall (like a broad M), or an abstract folded shape that suggests an M

**Concept sketches to try:**
1. Clean geometric M — two vertical strokes, one diagonal. Like a folded paper corner.
2. M from two triangles — like a play button split in half and mirrored.
3. Abstract M — curved strokes like a wave captured at its peak.

### 10.3 Color Palette & Design System

Already fully specified in plan.md (§5) — ONLYOFFICE Modern Dark inspired. No changes.

### 10.4 Window Title

Window title: **"Moment"** (not "Clip Pipeline")

### 10.5 Tray Tooltip

Format: `"Moment — {status}"` (already specified in tray spec)

---

## 11. Performance Targets (Updated)

### 11.1 In-Game FPS Impact

**Target:** Zero perceptible impact on in-game FPS.

| Activity | Expected Impact | Mitigation |
|----------|----------------|------------|
| Tray icon + tooltip | None | No GPU work. Idle event loop. |
| Toast notifications | None | Software-only. No GPU. |
| Game detection (`/proc` scan) | None | ~0.1ms per scan. 3s interval. |
| Clip Review Card popping up | None (brief) | Card uses `WA_ShowWithoutActivating`. No focus steal. |
| Encode (NVENC) during game | **Configurable** | Per-game profile: pause encode during game. Default: paused. |
| Upload (rclone) during game | None | CPU-bound but negligible. No GPU. Runs during game. |

**Design principle:** During game, Moment does NOTHING that could affect FPS. All GPU work is paused. All heavy I/O is paused. Tray + hotkey listener are the only active components.

### 11.2 Encode Speed

**Target:** <30 seconds to encode a 5-minute clip at 1080p.

| Hardware | CQ | Resolution | Estimated Time | Speed Factor |
|----------|-----|-----------|----------------|--------------|
| RTX 4080 | 23 | 1080p | ~15-20s for 5min clip | ~15-20x realtime |
| RTX 4080 | 23 | 1440p | ~25-35s for 5min clip | ~8-12x realtime |
| RTX 4080 | 23 | 4K | ~45-60s for 5min clip | ~5-7x realtime |
| RTX 4080 | 18 | 1080p | ~25-30s (higher quality, slower) | ~10x realtime |

**GPU semaphore:** Only one encode at a time. Queued encodes wait.

### 11.3 Upload Bandwidth / Ping Impact

**Target:** Uploads should not cause noticeable lag in online games.

| Configuration | Impact | Mitigation |
|---------------|--------|------------|
| rclone upload (default) | Uses all available bandwidth | Add `--bwlimit 5M` flag in uploader config |
| User gaming + upload active | Potential ping spike | Aggressive `--bwlimit 1M` during GAME_ACTIVE state |
| User not gaming | No limit | Full bandwidth used |

**Implementation:**

```python
# In uploader.py:
class Uploader:
    def _build_command(self, clip: Clip) -> list[str]:
        cmd = ["rclone", "copy", str(clip.encoded_path), f"{self.remote}:{self.bucket}/"]
        if game_monitor.is_game_active():
            cmd += ["--bwlimit", "1M"]       # Throttle during game
        else:
            cmd += ["--bwlimit", "5M"]       # Capped but faster (prevents saturating connection)
        return cmd
```

**Upload speed estimates** (5M limit, ~50MB encoded file):
- At 5Mbps: ~80 seconds for a 50MB file
- At 1Mbps (during game): ~7 minutes for a 50MB file
- At full bandwidth (~50Mbps upload): ~8 seconds

### 11.4 Startup Time

**Target:** <500ms to window visible + functional.

| Phase | Target Time | Notes |
|-------|-------------|-------|
| Python import | <100ms | All imports at top of file |
| QApplication init | <50ms | Must happen before window creation |
| SQLite open | <10ms | WAL mode, ~2MB for 500 clips |
| Window show | <100ms | Show empty frame immediately |
| Grid populate async | <200ms | Thumbnails load on scroll |
| **Total** | **<500ms** | |

### 11.5 Memory Budget (Confirmed)

| Area | Budget |
|------|--------|
| App at rest (idle) | <100MB RSS |
| During encode | <200MB RSS |
| Thumbnail LRU cache | 250 items max (~8MB) |
| SQLite (500 clips) | ~2MB |
| Video player | GPU memory (managed by QVideoWidget) |
| Temp transcodes | <500MB on disk, cleaned after use |

---

## 12. Remaining Gaps (Post-Decision)

| Gap | Section | Impact | Resolution |
|-----|---------|--------|------------|
| **GSR audio shim implementation** | §4 | High — required for multi-channel audio | Phase 3 implementation detail. Research GSR audio flags + PulseAudio parec during Phase 2. |
| **Pipeline must read selected storage provider at upload time** | §9, §13.4 | Medium — current pipeline likely hardcodes R2 remote | Wire into Pipeline during Phase 3 (new chunk 3.8). Until then, single hardcoded remote works for user's setup. |
| **YouTube OAuth setup wizard** | §1.2 | Medium — needed for YouTube provider | Add as a UX flow in Storage settings. Implement during Phase 4. |
| **Onboarding wizard UI** | §2.3 | Medium — needed for first-run experience | Phase 2c (new chunk 2.27). Single 4-step dialog. |
| **Privacy audit + config sanitization** | §2.2 | Medium — required before public launch | Phase 2c (new chunk 2.28) — earlier than originally planned. Strips personal artifacts before public exposure. |
| **Storage provider setup guides** | §9.2 | Low — documentation, not code | Write as docs before public release. |
| **Non-NVIDIA GPU support** | §5.3 | Low — AMD/Intel deferred | Revisit after v1. Test GSR `--vaapi` on AMD. |
| **OBS websocket backend** | §5.4 | Low — optional alternative | Deferred post-v1. |
| **Link sharing extensions** | §8.3 | Low — all post-v1 | Web gallery, view tracking, embed, batch, expiring links. |
| **In-game overlay (toast integration)** | §7.3 | Low — toast system already exists | Verify `WA_ShowWithoutActivating` works during fullscreen games. Test during Phase 2a (new chunk 2.12). |
| **Storage spillover UI** | §9.4 | Low — advanced feature | Implement during Phase 4 when multi-backend support is added. |
| **First-run GPU detection** | §5.3 | Low — AMD/Intel non-NVIDIA users see a message | Detect GPU on first launch. If non-NVIDIA: info toast "AMD GPU detected — Moment tested primarily on NVIDIA. Game capture may work but multi-channel audio is NVIDIA-only in v1." |

---

## 13. Phase Allocation Updates

### 13.1 New Chunks / Reassigned

| Unit | Deliverable | Spec Ref | Phase |
|------|------------|----------|-------|
*(Numbers below use the existing Phase 2a/2b/2c sub-numbering from plan.md §23. Inserting within each sub-phase.)*

| Unit | Deliverable | Spec Ref | Sub-Phase |
|------|------------|----------|-----------|
| 2.12 | In-game overlay behavior for toasts (`WA_ShowWithoutActivating`) | §7.3 | 2a |
| 2.20 | Storage provider base interface (`core/storage_providers.py`) | §9 | 2b |
| 2.27 | Onboarding wizard (4-step first-run dialog) | §2.3 | 2c |
| 2.28 | Privacy audit + configuration sanitization | §2.2 | 2c |
| 3.6 | GSR audio shim — parec-based multi-channel audio capture + error handling | §4, §4.5 | 3 |
| 3.7 | Audio source detection (game sink, Discord sink, default mic) + fallback handling | §4.4, §4.6 | 3 |
| 3.8 | Wire storage provider selection into Pipeline/Uploader (read from settings at upload time) | §9, §13.4 | 3 |
| 4.6 | Storage backend switcher UI (Settings → Storage tab) | §9.2 | 4 |
| 4.7 | Upload bandwidth throttling (--bwlimit 1M during game) | §11.3 | 4 |
| 5.8 | Music/soundtrack overlay in editor | §6.1 (#7) | 5 |
| 5.9 | Text/image overlay in editor | §6.1 (#8) | 5 |
| — | YouTube OAuth storage provider (future) | §1 | Post-v1 |
| — | Link sharing extensions (gallery, tracking, embed, batch, expiring) | §8.3 | Post-v1 |
| — | Non-NVIDIA GPU support (AMD/Intel) | §5.3 | Post-v1 |
| — | OBS websocket backend | §5.4 | Post-v1 |

### 13.2 Phase 2 Scope (Updated)

With the new chunks added:
- **Phase 2a:** 2.1–2.12 (12 units — original 11 + in-game overlay behavior as 2.12)
- **Phase 2b:** 2.13–2.21 (9 units — original 8 + storage provider interface as 2.20, shifted)
- **Phase 2c:** 2.22–2.30 (9 units — original 7 + onboarding wizard + privacy audit)

Total Phase 2: ~30 units over an estimated **5–7 sessions**.

### 13.3 Editor Evolution

The editor starts with 4 features in Phase 2b and grows to 8 by Phase 5:

| Phase | Editor Features | Notes |
|-------|----------------|-------|
| **2b** | Trim, Split, Speed, Audio Mix | Core editor. No placeholder buttons for deferred features. UI shows only what's available. |
| **3** | + Filters, + Crop/Rotate | Features appear as new buttons in the editor toolbar. No layout change — buttons fill into existing island. |
| **5** | + Music, + Overlays | Features appear as new buttons. Editor toolbar now has all 8 features. |

**No dead buttons.** Each feature appears ONLY when it's implemented. This avoids confusing users with grayed-out/unimplemented controls.

### 13.3 Removed from Spec

| Feature | Reason |
|---------|--------|
| Chroma key | Niche. Removed from editor. |
| Merge | Excessive for short clips. Deferred indefinitely. |
| Ken Burns | Over-engineered. Removed. |
| GIF export | Legacy format. WebM/MP4 standard. Removed. |
| Medal-style persistent overlay | User prefers brief toast-based approach. |

---

## 14. Verification / Acceptance Criteria

1. First-run wizard guides new user through setup (storage, games, hotkeys)
2. Clips auto-tagged with detected game name
3. Audio has separate tracks: game, mic, Discord (with GSR shim)
4. Editing suite has exactly 8 features: trim, split, speed, audio mix, filters, crop, music, overlays
5. No in-game FPS impact when encoding is paused (per game profile)
6. Upload throttles during game (--bwlimit 1M)
7. R2 auto-upload works as before + 4 additional backends selectable
8. "Moment" brand used everywhere: window title, tray, icon, .desktop file
9. Minimalist "M" icon replaces old clipboard icon
10. Link sharing system works with extensible URL handler interface
11. Privacy audit: no hardcoded personal paths, no user-identifiable logging
12. All post-v1 features (YouTube OAuth, link extensions, AMD support) documented in `docs/roadmap.md`
