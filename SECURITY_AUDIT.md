# Moment — Security Audit Report

**Date**: 2026-05-29  
**Repository**: `moment` (`/home/chasem/Projects/moment`)  
**Analysis**: Full source review of all Python source files (73 files) plus dependency/supply-chain analysis

---

## Overall Risk: 🟠 ELEVATED

| Severity | Count | Key Findings |
|----------|-------|-------------|
| **Critical** | 1 | Discord slash commands expose ALL clips with no auth |
| **High** | 4 | Discord token in plaintext DB, MCP auth bypass, Webhook URL leakage, subprocess arg injection via Store |
| **Medium** | 9 | No CSRF on MCP, no rate limiting, arbitrary config keys, symlink in import/export, upload no deadline, rclone config leakage in logs, retention data loss, ClipVisibility is a stub, no signed URLs |
| **Low** | 7 | Log files contain sensitive data, no encryption at rest, null byte handling fragile, /proc scanning silent failure, DISPLAY env partial mitigation, unvalidated media import, game monitor path leakage |
| **Info** | 5 | SQL injection safe, shell injection safe, path traversal partially mitigated, HTTPS enforced, DB perms 0600 |

---

## 1. 🔴 CRITICAL — Discord Slash Commands Have Zero Access Control

**Files**:
- `src/moment/core/discord_bot.py:153-273` — all slash commands
- `src/moment/core/discord_bot.py:275-295` — `_build_clip_embed()` includes R2 URL

**Issue**: Every user in the Discord guild can run `/recent`, `/stats`, `/search`, and `/clip` commands. These commands:
- List ALL clips with titles, durations, game names, sizes, statuses, and **R2 URLs** (line 169: `url_part = f"  —  [🔗]({clip.r2_url})"`)
- The `/clip` detail embed includes the full R2 URL (line 292)
- Partial ID prefix matching (`c.id.startswith(clip_id)` at line 256) lets anyone brute-force clip IDs character by character

**Impact**: Any Discord user (including guests) can enumerate the entire clip library. R2 URLs in responses give direct access to video content — no auth required.

**Fix**:
- Restrict slash commands to specific roles or user IDs
- Require the interaction user to be the clip owner (store a Discord user ID per clip)
- Remove partial-ID matching (exact match only)
- Never expose R2 URLs in ephemeral messages — require explicit opt-in per clip

---

## 2. 🔴 HIGH — Discord Bot Token in Plaintext

**Files**:
- `src/moment/core/config.py:90-110` — `Config.get()` returns raw JSON value
- `src/moment/core/store.py:281-333` — migration reads token from settings table

**Issue**: The Discord bot token is stored as plaintext in the SQLite `settings` table. In `_migrate_discord_token()` (store.py:281), the token is read from the DB, then optionally moved to keyring. If `keyring` is not installed (it's in `[bot]` optional deps, not required), the token **stays in the DB permanently**. The `MOMENT_DISCORD_TOKEN` env var is also passed in clear.

**pyproject.toml** shows `keyring>=25` is an **optional** dependency under `[bot]` — users who install `moment[all]` or `moment[bot]` get it, but `pip install moment` bare does NOT.

**Impact**: Any process with filesystem access to `~/.config/moment/clips.db` (mode 0600) can extract the token — root, other processes running as same user, backup tools.

**Fix**:
- Make `keyring` a hard dependency for the bot entry point (`main.py` guard)
- Never fall back to keeping the token in the DB — if keyring is unavailable, refuse to start the bot
- Zero-clear token strings after use (`token = ""` after `client.start(token)`)
- Warn at startup if token is readable by other processes

---

## 3. 🔴 HIGH — MCP Auth Middleware Can Be Bypassed

**File**: `src/moment/mcp/server.py:136`

```python
is_mutation = any(tool in path for tool in _MUTATION_TOOLS)
```

**Issue**: The auth middleware uses **Python's `in` substring operator** to check if the request path contains a mutation tool name. Crafted paths like:
- `/tools/enqueue_upload_malicious`
- `/tools/save_game_profile_backdoor`

would match and pass through without authentication. Additionally:
- The middleware accesses `server._app` / `server.app` — both private/protected attributes with no stability guarantee across fastmcp versions
- No early return for non-matching paths — read-tool paths still hit the middleware (wasted overhead)

**Impact**: An attacker can bypass mutation auth by including the tool name as a substring in a different endpoint path.

**Fix**:
- Use **exact path matching** against known tool routes (set literal, not substring `in`)
- Reject unknown paths early with 404 before auth check
- Add unit tests verifying auth rejection for bypass attempts like `/tools/FORMAT_AND_WIPE_DB`

---

## 4. 🔴 HIGH — Webhook URLs Exposed Via Store API

**File**: `src/moment/core/store.py:820-832`

```python
def list_webhooks(self) -> list[Webhook]:
    return [Webhook(url=r["url"], ...) for r in rows]
```

**Issue**: `Store.list_webhooks()` returns full webhook URLs including the Discord webhook token. While the MCP tool redacts them (`mcp/tools.py:185-197`), the Store method can be called directly by any code path.

Full Discord webhook URL format: `https://discord.com/api/webhooks/<id>/<token>`. Anyone with this URL can post arbitrary messages to the Discord channel.

**Impact**: Webhook token leakage allows unauthorized message posting. An attacker who chains MCP bypass (finding #3) with this can enumerate all webhook URLs via MCP.

**Fix**:
- Store only the webhook ID, reconstruct the full URL at dispatch time using a stored secret
- Or encrypt webhook URLs at rest with `cryptography.fernet`
- Never pass full webhook URLs outside the dispatch layer
- Log an audit trail of all webhook URL access

---

## 5. 🔴 HIGH — Internal Filesystem Paths Leaked via MCP

**File**: `src/moment/mcp/tools.py:126-158`

```python
"source_path": str(clip.source_path),
"encoded_path": str(clip.encoded_path) if clip.encoded_path else None,
"thumb_path": str(clip.thumb_path) if clip.thumb_path else None,
```

**Issue**: The `get_clip` MCP tool returns absolute filesystem paths (`/home/user/Videos/Moment/...`). When mutations are enabled, an attacker can:
1. Learn the user's home directory and directory structure
2. Use `save_game_profile` to craft audio device values that inject into subprocess commands

**Impact**: Information disclosure of filesystem layout, enabling targeted attacks.

**Fix**:
- Strip or relativize paths in MCP responses (return only filenames or relative paths)
- Never expose absolute paths over network-accessible APIs
- Add a `--safe-paths` flag that replaces paths with placeholder names

---

## 6. 🟡 MEDIUM — Audio Device / Tag Name Injection in Store Layer

**File**: `src/moment/core/store.py:883-908` — `save_game_profile()`

**Issue**: `game_device` and `mic_device` values from `GameProfile.audio_config` are validated at the MCP boundary and UI, but `Store.save_game_profile()` itself has **zero input validation**. An attacker who can write to the `game_profiles` table directly (via MCP bypass, DB write, or migration) can inject arbitrary flag arguments into the `gpu-screen-recorder` subprocess.

Without `shell=True`, injection is limited to flag injection (e.g., `-o /tmp/evil`, `--output /dev/shm/malicious`), not arbitrary command execution.

Similarly, `tag` values in `Store.save_clip()` have no character restrictions — tags are stored as JSON arrays and echoed into MCP responses, presenting a stored XSS vector for MCP clients.

**Impact**: Subprocess flag injection leading to file write to arbitrary paths. Stored metadata injection into MCP responses.

**Fix**:
- Move validation into `Store.save_game_profile()` and `Store.save_clip()` itself
- Whitelist allowed characters: `^[a-zA-Z0-9_., /-]+$` for device names
- Whitelist `^[a-zA-Z0-9 _-]+$` for tag values
- Use `--` sentinel before user-controlled subprocess values where possible

---

## 7. 🟡 MEDIUM — RNNoise Filter Path Injection

**File**: `src/moment/core/noise_suppression.py:182-197`

**Issue**: `self._model_path` is interpolated into an ffmpeg filtergraph string: `f"arnndn=m={valid_path}"`. Validation at line 184 uses `validate_arg` which is **bypassed** if the model path is set via config or programmatic API (not via MCP). Line 195 silently falls back to `arnndn` (no arguments) when validation fails, masking errors.

**Impact**: Arbitrary ffmpeg filter expression injection if `model_path` is attacker-controlled. Could inject `volume=0,[out]` or other filter keywords.

**Fix**:
- Validate model path at `NoiseSuppressor.__init__()` boundary
- Only accept paths matching `^[a-zA-Z0-9_./-]+\.rnn$`
- Verify `os.path.isfile(valid_path)` at construction time, not lazily
- Remove the silent fallback to `arnndn` on validation failure (fail closed)

---

## 8. 🟡 MEDIUM — No CSRF Protection on MCP HTTP Transport

**File**: `src/moment/mcp/main.py:73-76`

**Issue**: The MCP server binds to `127.0.0.1` but has no CSRF protection. A malicious website can make `fetch("http://127.0.0.1:8742/...")` requests. Even without CORS, `fetch` with `mode: 'no-cors'` still delivers a simple GET/POST. Read tools require no auth, so any website the user visits can enumerate clips.

**Impact**: Any website the user visits can trigger MCP read operations (list clips, get stats, read settings). Combined with token leakage (e.g., stored in browser local storage by a local integration), mutation operations are also exposed.

**Fix**:
- Add CORS middleware that rejects cross-origin requests (allow `Origin: null` or same-origin only)
- Require `X-Requested-With: XMLHttpRequest` header
- Validate `Origin` header on all endpoints
- Document that HTTP transport should only be used behind a local reverse proxy with auth

---

## 9. 🟡 MEDIUM — No Rate Limiting on Webhook Dispatch

**File**: `src/moment/mcp/tools.py:256-285`

**Issue**: `test_webhook()` sends a Discord webhook with no rate limiting. Calling it 100 times/second will:
- Hit Discord's rate limits (causing the caller's IP to be banned)
- Flood the target Discord channel with test messages
- Spam the channel owner's notifications

**Impact**: DoS against the user's Discord channel. Could be weaponized via CSRF (finding #8) for sustained attack.

**Fix**:
- Add per-webhook cooldown (minimum 60 seconds between calls)
- Track last test time per webhook ID in memory
- Log all webhook test invocations

---

## 10. 🟡 MEDIUM — Arbitrary Config Key Writes

**File**: `src/moment/core/config.py:112-123`

```python
def set(self, key: str, value: Any) -> None:
    serialised = json.dumps(value)
    conn.execute("INSERT OR REPLACE INTO settings ...")
```

**Issue**: `Config.set()` accepts ANY key with no whitelist. A caller could write:
- `path_db_dir` → redirect database to attacker-controlled location
- `path_log_dir` → redirect logs to exfiltratable location
- `gsr_replay_audio_device` → override audio device with malicious value
- Any arbitrary key with any value

The `SettingsDialog` (`settings_dialog.py:630-715`) writes dozens of keys, but only keys in the settings form — the API itself has no guard.

**Impact**: Privilege escalation via config poisoning. An attacker who can write one key can redirect storage paths or override security-relevant settings.

**Fix**:
- Implement a key whitelist for `Config.set()` with documented security impact per key
- Validate path overrides resolve to expected directories (no symlink escape)
- Log every `Config.set()` call with caller identity in debug builds

---

## 11. 🟡 MEDIUM — Uploader Has No Total Deadline

**Files**: `src/moment/core/uploader.py:95-118`

**Issue**: The uploader retries up to 3 times with delays of 5s, 30s, and 300s. However:
- There is **no total timeout** — a persistently failing upload can block the pipeline for 335 seconds
- The `rclone copy` subprocess has a per-call `timeout=600` (10 minutes)
- During retry delays, the thread holds a worker pool slot
- If 3 consecutive uploads fail, the pipeline could be starved for ~16 minutes total

**Impact**: Degraded availability — failed uploads consume pipeline workers for extended periods, starving other clips.

**Fix**:
- Add a total deadline per upload (15 minutes max)
- Implement circuit breaker: after N consecutive failures, back off globally
- Make upload failures non-blocking (error task → retry queue)

---

## 12. 🟡 MEDIUM — rclone Config/Remote Name Leakage

**File**: `src/moment/core/uploader.py:152-167`

**Issue**: The uploader logs the destination path including the remote name at INFO level:
```python
logger.info("No base_url set — returning rclone path %s", dest)
```
where `dest = f"{self._remote}:{self._bucket}/{remote_path}"`. The remote/bucket names are also stored in the Config DB as plaintext.

**Impact**: Storage provider topology revealed via logs and config DB. Remote name alone is low-value, but combined with other leaks helps attackers map infrastructure.

**Fix**:
- Never log rclone remote/bucket names at INFO level (DEBUG only)
- Log only the filename portion, not the full remote path

---

## 13. 🟡 MEDIUM — Import/Export Symlink Following

**File**: `src/moment/core/import_export.py:265`

```python
shutil.copy2(src, out)
```

Where `src` comes from `clip.encoded_path` (user-controlled via importer or clips table). If `encoded_path` is a symlink, `shutil.copy2` follows it and copies the target file.

**Impact**: An attacker who can set `encoded_path` (via MCP update, DB write, or migration) can export any file the user has read access to.

**Fix**:
- Resolve `clip.encoded_path` with `Path.resolve()` before copying
- Verify resolved path is within expected directories
- Add a `Path.is_symlink()` check and reject symlink targets outside allowed dirs

---

## 14. 🟡 MEDIUM — Retention Purges Data Without Backup

**File**: `src/moment/core/retention.py:163, 194`

**Issue**: The retention manager calls `clip.source_path.unlink()` and `clip.encoded_path.unlink()` to permanently delete files. `ERROR`/`CORRUPT` clips are still deleted on age-based retention — the user may want to keep corrupted files for debugging.

**Impact**: Permanent data loss. No undo or trash for retention-purged files.

**Fix**:
- Move to a trash directory instead of deleting immediately
- Add a "retention hold" flag on clips (independent of `protect_from_retention`)
- Skip deletion for `ERROR`/`CORRUPT` clips unless explicitly confirmed
- Implement a 30-day trash before permanent removal

---

## 15. 🟡 MEDIUM — ClipVisibility Is a Stub With Zero Enforcement

**Files**:
- `src/moment/core/models.py:32-37` — enum definition
- `src/moment/core/store.py:193, 231, 448, 1242` — read/write in DB
- `src/moment/mcp/tools.py:151` — serialized in responses

**Issue**: `ClipVisibility` (PUBLIC / UNLISTED / PRIVATE) is defined, stored in the database, and serialized in MCP responses — but **never enforced anywhere**. There is no filtering by visibility, no access control logic, no different behavior based on it. All clips are returned by all APIs regardless of their visibility setting.

Additionally, the `uploader.py:172-178` URL builder (`_build_url()`) simply concatenates `base_url + remote_path` — there is no support for **signed/expiring URLs**, pre-signed tokens, or any access control mechanism on the cloud provider side. If the bucket is public-read, every clip URL is accessible to anyone with the link.

**Impact**: The visibility field is misleading — users who set a clip to PRIVATE get a false sense of security. All shared URLs are static and permanent.

**Fix**:
- Implement actual enforcement: filter MCP/Discord responses by visibility level
- Add user authentication to MCP (clip ownership checks)
- Add support for pre-signed (time-expiring) URLs on the cloud provider side
- Document that the R2 bucket should be private with per-object access control

---

## 16. 🟢 LOW — No Encryption at Rest for Clip Files

**Files**:
- `~/.local/share/moment/encoded/*.mp4` — encoded clips
- `~/.local/share/moment/thumbnails/*.jpg` — thumbnails
- `~/Videos/Moment/*.mkv` — source recordings
- `~/Pictures/Moment/*.png` — screenshots

**Issue**: All media files are stored unencrypted. Any process with the user's filesystem access can read, copy, or exfiltrate clip content.

**Impact**: Data disclosure via filesystem access. Gameplay footage (potentially containing sensitive on-screen content) is unprotected.

**Fix**:
- Offer optional per-session encryption key stored in system keyring
- Encrypt clips before upload (client-side encryption, e.g., age or GPG)
- Document that clip files are unencrypted and recommend full-disk encryption (LUKS, fscrypt)

---

## 17. 🟢 LOW — Log Files Contain Sensitive Data

**File**: `src/moment/utils/logging.py:43-89`

**Issue**: Log files at `~/.local/share/moment/moment.log` contain:
- Audio device names and paths
- Game profile configurations
- File paths and clip metadata
- Webhook dispatch status and error messages
- Full ffmpeg command lines (including filtergraphs with user content)
- Retention purge actions

These logs are plaintext, rotated at 10MB (3 backups), and have no access restrictions beyond filesystem permissions.

**Impact**: Information disclosure via log file access. Standard forensic target.

**Fix**:
- Prevent logging file paths at INFO level (use DEBUG only)
- Redact audio device names and game profile details in INFO logs
- Set log file permissions to 0600
- Add log sanitization utility for sensitive data patterns

---

## 18. 🟢 LOW — Null Byte Handling in Stem Sanitization

**File**: `src/moment/utils/system.py:129-149`

```python
cleaned = stem.replace("..", "").lstrip("/").lstrip("\\")
cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", cleaned)
```

**Issue**: The `sanitize_stem()` function:
- Replaces `..` with empty string (fragile — `...` becomes `.`, enabling partial traversal)
- Null bytes (`\x00`) are replaced with `_` by the regex rather than rejected outright
- Triple-dot encoding (`...`) becomes `.` after `..` removal, which isn't a traversal vector but shows the approach is fragile

**Impact**: Low on modern Linux/Python (null bytes are safe), but the `replace("..", "")` approach can't handle `....//` or `..\` variants.

**Fix**:
- Use `Path(stem).resolve()` after sanitization to verify it stays within expected parent
- Reject suspicious stems entirely rather than trying to "cleanse" them
- Use `os.path.basename()` as additional safeguard

---

## 19. 🟢 LOW — /proc Scanning Without Permission Check

**File**: `src/moment/core/game_monitor.py:168-189`

**Issue**: The game monitor reads `/proc/*/comm` files to detect game processes. On hardened systems (`hidepid=2` mount option), these reads fail silently with PermissionError caught at line 178, causing game detection to not work without warning.

**Impact**: Game detection silently fails on hardened systems. Not a vulnerability, but degrades UX without feedback.

**Fix**:
- Log a warning at INFO level if `/proc` is restricted on first scan
- Document the `/proc` access requirement

---

## 20. 🟢 LOW — DISPLAY Environment Variable Validation

**File**: `src/moment/core/screenshot.py:88-89`

**Issue**: The `DISPLAY` env var is used as ffmpeg x11grab input source. Already partially mitigated by `_validate_display()` (screenshot.py:165-175) which checks against `^:[0-9]+(\.[0-9]+)?$` and falls back to `:0.0` on invalid input.

**Status**: 🟢 **Mitigated** — regex validation present.

---

## 21. 🟢 LOW — Unvalidated Media Import

**File**: `src/moment/core/import_export.py:113-116`

**Issue**: `import_file()` checks file existence and size, but MIME-type validation via `_check_mime_type()` is optional (graceful degradation when `python-magic` not installed — it's an optional dep: `moment[import-export]`). When neither `python-magic` nor `file(1)` is available, **any file type** passes through to ffprobe.

**Impact**: DoS via crafted file that crashes ffprobe, or information disclosure via ffprobe exif parsing.

**Fix**:
- Make `python-magic` a hard dependency for import functionality
- Verify magic bytes before calling ffprobe (not just MIME type string)
- Add maximum file size limit at the import boundary

---

## 22. 🟢 LOW — Game Monitor Path Leakage

**File**: `src/moment/core/game_monitor.py:175`

**Issue**: The game monitor reads `/proc/<pid>/comm` and `/proc/<pid>/cmdline` to identify running games. While this is standard Linux process enumeration, the game name is stored in the clip model and can be exposed via MCP/Discord APIs. If a game name contains sensitive metadata (e.g., paths, usernames), it gets propagated.

**Impact**: Low — process names are generally low-sensitivity, but the data crosses trust boundaries (filesystem → DB → Discord API).

**Fix**:
- Validate/sanitize game names read from `/proc` against the same `validate_arg` regex
- Strip non-printable characters from `/proc` reads

---

## 23. ℹ️ INFO — ClipVisibility Stub Deployed but Unenforced

See #15 above for the full finding. This is flagged as MEDIUM due to the false sense of security it creates.

---

## 24. ℹ️ INFO — Cloud Provider Access Model (No Credential Exposure)

**Files**:
- `src/moment/core/uploader.py:40-67` — uploader constructor
- `src/moment/core/uploader.py:152-167` — rclone copy subprocess

**Finding**: Moment **does not store, see, or handle cloud credentials**. All cloud access goes through `rclone copy` as a subprocess. The user's rclone config (`~/.config/rclone/rclone.conf`) is managed entirely by rclone (typically mode 0600). Moment only stores:
- `rclone_remote` (default: `"r2"`) — the rclone remote profile name
- `rclone_bucket` (default: `"moment"`) — the bucket/container name
- `base_url` — optional public URL prefix for constructing share links

These three values can also be set via environment variables (`MOMENT_RCLONE_REMOTE`, `MOMENT_RCLONE_BUCKET`, `MOMENT_BASE_URL`).

**Privacy Guarantee**: Moment has zero direct HTTP client code. No `requests`, `urllib`, `httpx`, or `aiohttp` anywhere in the source. The only network calls are:
1. `rclone copy` subprocess (user-initiated uploads)
2. `discord.py` internal HTTP (Discord bot connection and webhook dispatch)

**No telemetry, no auto-update checker, no analytics, no crash reporting, no license validation, no phone-home of any kind.**

---

## 25. ℹ️ INFO — Deployment Security Posture

### No Auto-Update / No Phone-Home

Moment has no auto-update mechanism, no PyPI version check, no GitHub release checker. Updates are manual only — good for privacy (no beacon), bad for security patches (user must manually update).

### Systemd Integration

No built-in systemd service files. The bot and MCP server run as foreground processes tied to a terminal session. For production use:
- Write a `moment-bot.service` and `moment-mcp.service` with `Restart=on-failure`
- Use `DynamicUser=` or `ProtectHome=` for sandboxing
- Set `PrivateTmp=true`, `NoNewPrivileges=true`, `CapabilityBoundingSet=~CAP_NET_RAW`

### Backup Strategy

Critical data paths:
- `~/.config/moment/clips.db` — all metadata, tokens, webhook URLs, config (essential)
- `~/.config/moment/moment.log` — troubleshooting (replaceable)
- `~/.config/rclone/rclone.conf` — cloud credentials (NOT backed up by Moment)
- `~/.local/share/moment/encoded/` — encoded clip files (large, can be re-encoded from source)
- `~/Videos/Moment/` — source recordings (largest, can be re-recorded)
- `~/Pictures/Moment/` — screenshots

Recommended backup strategy:
- Use `restic` or `borg` for encrypted, deduplicated backups
- Back up the config DB daily (it's small and critical)
- Back up encoded clips weekly (they represent editing effort)
- Source recordings can be treated as ephemeral (auto-purged by retention)

### rclone Credential Isolation

- `~/.config/rclone/rclone.conf` should be chmod 0600
- rclone supports encrypted config (`rclone config --config-encrypt`) — strongly recommended
- Never set `MOMENT_RCLONE_REMOTE` to a remote with broader permissions than needed
- Consider using a dedicated rclone remote with a service account token scoped to a single bucket

### Network Exposure

- MCP HTTP binds to `127.0.0.1:8742` by default — do not expose to the network
- Discord bot connects outbound only (no inbound ports needed)
- Webhook URLs are outbound POSTs only
- No ports need to be open in a firewall for Moment to function

---

## 26. ℹ️ INFO — Shared Clip Mechanics

### How Sharing Works Today

1. Clip is encoded to `~/.local/share/moment/encoded/<id>.mp4`
2. Uploader calls `rclone copy <local_path> <remote>:<bucket>/<id>.mp4`
3. `_build_url()` constructs a URL: `{base_url}/{remote_path}` or falls back to `{remote}:{bucket}/{path}`
4. The R2 URL is stored in the `clips` table as `r2_url`
5. Discord bot and MCP tools serve this URL to any caller

### Privacy Implications

- **No access control on the cloud side**: If the bucket is public-read, anyone with the URL can access the clip
- **No signed/expiring URLs**: All shared URLs are permanent and immutable
- **ClipVisibility is unenforced**: Setting a clip to PRIVATE does nothing — the URL still exists and can be shared
- **No audit trail**: No tracking of who accessed a shared clip or how many times
- **Webhook sharing**: Discord webhooks contain full channel tokens — anyone with the webhook URL can post to the channel

### Recommendations for Privacy-Preserving Sharing

- Configure the R2 bucket as **private** and use Cloudflare Access / pre-signed URLs
- Add signed URL support to the uploader (time-expiring tokens per clip)
- Enforce `ClipVisibility` at the API layer (filter clips by visibility before returning)
- Add clipboard-scoped access control: only the user who created a clip can share its URL
- Consider an optional proxy layer that validates access before redirecting to the cloud URL

---

## ⚠️ Bandit Suppression Issue

**File**: `pyproject.toml` — no bandit section found

**Issue**: The codebase uses `# nosec` annotations per-call which is the correct approach, but `B603` (subprocess without shell=True) is annotated on calls that ARE safely tokenized. The sheer volume of subprocess calls (30+) makes it hard to distinguish safe calls from potentially vulnerable ones.

**Fix**: Use a wrapper function for all subprocess calls that centralizes safety checks and reduces the annotation surface.

---

## Defenses Confirmed Effective

| Control | Status | Evidence |
|---------|--------|----------|
| **SQL injection** | 🟢 **None found** | All queries use `?` parameterization. Sort columns whitelisted (`store.py:597-603`). |
| **Shell injection** | 🟢 **None found** | Zero `shell=True` calls in the entire codebase. All subprocess calls use tokenized arg lists. |
| **Path traversal** | 🟢 **Mitigated** | `sanitize_stem()` strips `..`, leading `/`, restricts to `[a-zA-Z0-9._-]`. Add null byte and triple-dot handling. |
| **Webhook URL security** | 🟢 **HTTPS enforced** | `_is_secure_url()` at `store.py:141-148` rejects non-`https://` URLs. UI also validates. |
| **DB file permissions** | 🟢 **0600** | `store.py:271-272` — `os.chmod(self._db_path, 0o600)` on existing DBs. |
| **Hardcoded secrets** | 🟢 **None** | No API keys, passwords, or credentials in source code. |
| **No phone-home** | 🟢 **Confirmed** | Zero HTTP client libraries in source — only subprocess rclone + discord.py internal. |
| **DISPLAY validation** | 🟢 **Mitigated** | `_validate_display()` regex check in `screenshot.py:165-175`. |
| **validate_arg() guard** | 🟢 **Present** | `utils/system.py:101-126` — regex-based input validation for subprocess args. Used in `recorder_controller.py` and `mcp/tools.py`. Not used in `store.py` or `config.py`. |
| **CSP / Qt WebEngine** | 🟢 **N/A** | Moment does not use QWebEngine or render HTML content. XSS surface is minimal. |

---

## Dependency CVE Check

| Dependency | Version | Type | Notes |
|-----------|---------|------|-------|
| PyQt6 | latest | Hard | No critical CVEs |
| discord.py | >=2.4 | Optional (`[bot]`) | No critical CVEs |
| fastmcp | >=1.0 | Optional (`[mcp]`) | No critical CVEs |
| keyring | >=25 | Optional (`[bot]`) | No critical CVEs |
| python-magic | >=0.4 | Optional (`[import-export]`) | No critical CVEs |

**Note**: `keyring`, `discord.py`, `fastmcp`, and `python-magic` are all **optional dependencies**. Users who install bare `moment` without extras only get PyQt6. This reduces the attack surface but also means security-sensitive features (keyring for token storage) may be silently unavailable.

---

## Attack Tree

```
┌─ Attacker Goal: Exfiltrate private clip data ────────────────────┐
│                                                                   │
│  1. Network Access ───────────────────────────────────────────────┤
│  ├─ MCP HTTP (localhost:8742) ───→ read tools (no auth)          │
│  │   └─ list_clips, get_clip → clip metadata + R2 URLs           │
│  │   └─ save_game_profile → audio device injection → GSR flags   │
│  │                                                               │
│  2. Discord Access ──────────────────────────────────────────────┤
│  ├─ /clip XXXX → enumerate clip IDs via prefix matching          │
│  ├─ /recent → list latest clips with R2 URLs                     │
│  │                                                               │
│  3. Filesystem Access ───────────────────────────────────────────┤
│  ├─ ~/.config/moment/clips.db → Discord token, webhook URLs      │
│  ├─ ~/.config/moment/clips.db → MCP API token, rclone config     │
│  ├─ ~/.local/share/moment/* → clip content files                 │
│  └─ ~/.config/moment/moment.log → paths, device names            │
│                                                                   │
│  4. Supply Chain ─────────────────────────────────────────────────┤
│  └─ Discord bot env var → token in process env → /proc leakage   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Remediation Priority

| # | Finding | Effort | Risk | Suggested Fix |
|---|---------|--------|------|---------------|
| 1 | Discord commands no auth | 2h | 🔴 Critical | Role-gate + owner check + remove prefix matching |
| 2 | MCP auth substring bypass | 30m | 🔴 High | Exact path match instead of `in` operator |
| 3 | Webhook URLs in Store response | 1h | 🔴 High | Return redacted URLs, reconstruct on use |
| 4 | Internal paths in MCP output | 1h | 🔴 High | Strip or relativize paths in responses |
| 5 | Discord token in plaintext DB | 2h | 🔴 High | Make keyring a hard dep, zero-clear tokens |
| 6 | No CSRF on MCP HTTP | 1h | 🟡 Medium | CORS middleware + require `X-Requested-With` |
| 7 | No rate limiting on webhooks | 30m | 🟡 Medium | Per-webhook cooldown + audit log |
| 8 | Arbitrary Config key writes | 1h | 🟡 Medium | Key whitelist + path validation |
| 9 | Uploader no deadline | 1h | 🟡 Medium | Total deadline + circuit breaker |
| 10 | Retention no backup | 2h | 🟡 Medium | Trash directory for retention-deleted files |
| 11 | Symlink in import/export | 30m | 🟡 Medium | Resolve paths, check for symlinks |
| 12 | ClipVisibility enforcement | 3h | 🟡 Medium | Filter by visibility, add signed URL support |
| 13 | Log file sensitive data | 2h | 🟢 Low | Redact paths in INFO, set 0600 perm |
| 14 | No encryption at rest | 4h | 🟢 Low | Optional encryption + document FDE requirement |
| 15 | Null byte in stem sanitization | 15m | 🟢 Low | Reject stems with suspicious characters |
| 16 | Audio device injection in store | 30m | 🟡 Medium | Move validation into Store layer |
| 17 | Signed/expiring URLs | 4h | 🟡 Medium | Add pre-signed URL support to uploader |

---

## Summary

Moment has an **elevated** security posture. The critical finding is the Discord bot exposing all clip data with no access control. The high-severity findings center on secret/key exposure and MCP auth weaknesses. The medium findings are mostly about hardening subprocess boundaries and adding rate/access controls.

**Key recommendations**:
1. **Fix Discord slash command auth immediately** — clip data should not be visible to arbitrary guild members
2. **Fix MCP auth middleware** — substring matching is trivially bypassed
3. **Add CSRF protection** to MCP HTTP transport
4. **Encrypt secrets at rest** — Discord token, MCP token, webhook URLs
5. **Add rate limiting** to all external-facing mutation operations
6. **Move input validation to the Store layer**, not just the API boundary
7. **Add total deadline to uploads** to prevent pipeline starvation
8. **Add signed URL support** for privacy-preserving clip sharing
9. **Enforce ClipVisibility** — don't let it be a misleading stub
10. **Enable full-disk encryption** recommended for clip data protection

**Privacy guarantee**: Moment has no telemetry, no auto-update, no analytics, no crash reporting, and no phone-home of any kind. The app makes zero direct HTTP requests using Python HTTP libraries — all network access is through subprocess rclone calls and discord.py's internal client.
