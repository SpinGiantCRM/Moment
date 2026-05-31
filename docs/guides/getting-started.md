# Getting Started with Moment

This guide walks you through your first Moment session — from launching the app to capturing and sharing your first clip.

> **Installation first:** If you haven't installed Moment yet, see the [README](../../README.md#installation) for setup instructions.

---

## First Launch

```bash
moment
```

On first launch, Moment:

1. Creates `~/.config/moment/clips.db` — your encrypted clip database
2. Opens the **Grid** page (empty — you haven't captured anything yet)
3. Starts in the system tray (look for the Moment icon)

> **Trouble launching?** If you see an error about `sqlcipher3`, make sure `libsqlcipher-dev` (or `sqlcipher` on Arch) is installed. See [Troubleshooting](#troubleshooting).

---

## Configure Recording

Before you can capture clips, you need to enable **GPU Screen Recorder (GSR)** replay mode.

### Step 1: Open Settings

Press **F10** or right-click the tray icon and select **Settings**.

### Step 2: Enable Instant Replay

In Settings → **Recording** tab:

| Setting | Recommended Value | Description |
|---------|-------------------|-------------|
| Enable GSR Replay | ✅ On | Start GSR in replay mode at launch |
| Replay Duration | 30 seconds | How much buffer to keep before the save |
| Quality | High | Video quality setting |
| FPS | 60 | Capture frame rate |
| Capture Monitor | Auto | Select display if you have multiple monitors |

Click **Apply**.

> GSR replay must be enabled *before* you start your game. It runs continuously in the background, keeping a rolling buffer.

---

## Capture Your First Clip

### Method 1: Hotkey (GSR Replay Enabled)

1. Launch your game
2. When something cool happens, press **F8** to save a 30-second replay
3. Moment encodes the clip (NVENC hardware acceleration) and shows a toast notification

| Hotkey | Action |
|--------|--------|
| F8 | Save a 30-second replay |
| F9 | Save a 60-second replay |

### Method 2: Manual Recording

In Settings → Recording, set **Post-Capture Action** to "Show recording page" and use the on-screen record button.

### What Happens Next

After saving a clip, Moment runs a pipeline:

```
GSR writes MKV → Clip detected → Encode (NVENC → MP4) → Generate thumbnail
                                                        → Optionally upload to cloud
                                                        → Appears in Grid
```

The clip appears in the **Grid** page once encoding completes (usually a few seconds).

---

## Find and Manage Clips

### Grid Page

Opened by default. Browse all clips with:

- **Search** by game name, date, or filename
- **Filter** by game or date range
- **Sort** by newest, oldest, or longest
- **Batch select** with Ctrl+B for multi-clip operations

### Player Page

Click any clip to open the player:

- **Play / Pause** — video preview
- **Trim** — cut start/end points
- **Favorite** ⭐ — star your best clips
- **Share** — copy shareable URL (if upload is configured)
- **Delete** — moves to Trash (soft delete)

### Stats Page

See aggregate statistics:

- Total clips, total duration
- Per-game breakdown
- Encoding time / upload success rate

### Trash Page

Recover or permanently delete soft-deleted clips. Empty Trash to free disk space.

---

## Configure Cloud Upload

Moment uses **rclone** to upload clips to cloud storage.

### Step 1: Install rclone

```bash
# See https://rclone.org/install/ for all platforms
sudo -v ; curl https://rclone.org/install.sh | sudo bash
```

### Step 2: Configure a Remote

```bash
rclone config
```

Follow the interactive setup for your provider (Backblaze B2, Cloudflare R2, AWS S3, etc.).

### Step 3: Enable Upload in Moment

1. Open **Settings** (F10)
2. Go to **Upload** tab
3. Set **Remote name** to your rclone remote (e.g., `r2`, `b2`, `s3`)
4. Set **Bucket/path** (e.g., `moment/clips`)
5. Click **Apply**

When Upload is enabled, every new clip is automatically uploaded after encoding.

---

## Hotkeys Reference

| Hotkey | Context | Action |
|--------|---------|--------|
| F8 | Anywhere (GSR running) | Save 30s replay |
| F9 | Anywhere (GSR running) | Save 60s replay |
| F10 | Anywhere | Open settings |
| Escape | Player / Settings | Back to Grid |
| Ctrl+B | Grid | Toggle batch selection mode |
| Ctrl+Shift+I | Grid | Invert selection |

---

## Directory Layout

| Path | Purpose |
|------|---------|
| Path | Purpose |
|------|---------|
| `~/.config/moment/` | Configuration and database |
| `~/.config/moment/clips.db` | Encrypted SQLite database (AES-256) |
| `~/.local/share/moment/encoded/` | Encoded MP4 clips |
| `~/.local/share/moment/thumbnails/` | Thumbnail JPEGs (lazy-loaded cache) |
| `~/.local/share/moment/crash/` | Crash dump files (diagnostic context) |
| `~/Videos/Moment/` | Raw GSR recordings (MKV before encoding) |

---

## Discord Bot

```bash
# Store your bot token (one time)
keyring set moment discord_bot_token

# Start the bot
moment bot
```

Slash commands: `/clip`, `/search`, `/recent`, `/stats`.

---

## MCP Server (AI Agent Access)

```bash
moment mcp                          # stdio mode (for AI agents)
moment mcp --http                   # HTTP on 127.0.0.1:8742
moment mcp --http --port 9000 --api-token "secret"  # With auth
```

---

## Troubleshooting

### "sqlcipher3 is not installed"

```bash
# Install the system library first:
sudo apt install libsqlcipher-dev    # Debian/Ubuntu
sudo pacman -S sqlcipher             # Arch
sudo dnf install libsqlcipher-devel  # Fedora

# Then reinstall Moment:
pip install --force-reinstall sqlcipher3
```

### "Database could not be opened"

```bash
# Check permissions
ls -la ~/.config/moment/
# Expected: encrypted SQLite (binary, not plaintext)

# If it's damaged, rename and restart:
mv ~/.config/moment/clips.db ~/.config/moment/clips.db.bak
moment
```

### "No NVENC encoder found"

```bash
# Check available encoders
ffmpeg -encoders | grep nvenc

# If empty, use software fallback:
ffmpeg -encoders | grep libx264
```

### Moment doesn't show in app launcher

```bash
# Install desktop integration (standalone):
curl -fsSL https://raw.githubusercontent.com/SpinGiantCRM/moment/main/install/install.sh | bash
```

---

## What's Next?

- **Per-game profiles:** Configure different recording settings per game
- **Webhooks:** Get Discord notifications when friends share clips
- **Video editor:** Trim, split, merge, add filters and overlays
- **GIF export:** Create optimized GIFs from your clips
- **`AGENTS.md`** — AI agent briefing for the full project picture
- **`ARCHITECTURE.md`** — Deep dive into system internals
