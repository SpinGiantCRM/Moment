# Moment Security Model

## Overview

Moment handles sensitive data: Discord bot tokens, webhook URLs, cloud storage credentials, and video files. Security is designed with **defense in depth** — encryption at rest, minimal attack surface, and secret redaction.

**Current security posture:** Active development.

---

## 1. Encryption at Rest

### Database Encryption (SQLCipher)
- **Mandatory:** `sqlcipher3` is required — the store will not open without it
- **Algorithm:** AES-256-CBC via SQLCipher
- **Key storage:** OS keyring (`keyring` library), stored under `moment/db_encryption_key`
- **Key generation:** 256-bit random hex key generated on first access
- **No fallback:** If keyring or sqlcipher3 is unavailable, `Store.__init__()` raises `RuntimeError`
- **File permissions:** DB file set to `0o600` (owner read/write only)

### Webhook URL Encryption (Fernet)
- **Algorithm:** AES-128-CBC + HMAC-SHA256 (Fernet)
- **Key storage:** OS keyring (`moment/webhook_encryption_key`)
- **Key migration:** Legacy keys in `settings` table are migrated to keyring on first access and deleted from DB
- **No fallback:** Failed decryption raises `RuntimeError`
- **Redacted display:** Webhook URLs in the UI show `[REDACTED]` token portion

### Startup Health Check
On every `Store` initialization:
1. Verifies sqlcipher3 is importable
2. Verifies keyring is available
3. Runs Fernet encrypt/decrypt round-trip test (hard fail)
4. Checks DB file header — warns if plaintext SQLite detected

---

## 2. Credential Management

| Secret | Storage | Source |
|--------|---------|--------|
| Discord bot token | OS keyring (`moment/discord_bot_token`) | Migrated from settings table on first access |
| DB encryption key | OS keyring (`moment/db_encryption_key`) | Auto-generated on first access |
| Webhook encryption key | OS keyring (`moment/webhook_encryption_key`) | Auto-generated or migrated from legacy |
| MCP API token | CLI argument or env var | User-provided |

**Anti-patterns eliminated:**
- ❌ No `MOMENT_DISCORD_TOKEN` env var — token is keyring-only
- ❌ No `webhook_encryption_key` in settings table — migrated to keyring
- ❌ No plaintext fallback paths — all encryption failures are hard errors

---

## 3. Input Validation

### Config Key Whitelist
`Config.set()` validates against `_ALLOWED_KEYS` (exact match) or `_ALLOWED_PREFIXES` (`path_*`, `gsr_*`). Unknown keys are rejected with `ValueError` and logged with caller context.

### Path Containment
`path_*` config values must resolve within `$HOME` or `/tmp`. Path traversal attempts are rejected.

### Webhook URL Validation
All webhook URLs must start with `https://`. HTTP URLs are rejected.

### MIME Type Validation
Import/Export uses `python-magic` or `file(1)` to validate file types before import.

---

## 4. Authentication

### MCP Server
- **ALL endpoints** require Bearer token in `Authorization` header
- **Scoped tokens:** `--allow-mutations` flag grants write access; without it, token is read-only
- **Token comparison:** Uses `hmac.compare_digest()` for constant-time comparison
- **Token storage:** CLI arg `--api-token` or `MOMENT_MCP_TOKEN` env var

### Discord Bot
- **Role-based access:** `discord_allowed_roles` config restricts slash commands
- **Rate limiting:** SQLite-backed persistent rate limiting
- **Token:** OS keyring only (no env var)

---

## 5. Logging & Audit

### Secret Redaction
All sensitive values are redacted from logs:
- Discord tokens
- Webhook URLs (token portion → `[REDACTED]`)
- Encryption keys
- File paths (in some contexts)
- R2 URLs (in some contexts)

### Audit Trail
- URL copy history in `url_history` table
- Webhook delivery logs in `webhook_log` table
- Config write rejections logged with caller frame info

### Caller Tracking
`Config.set()` logs the caller's file:line:function for every rejected write via `inspect.stack()`.

---

## 6. Network Security

### MCP Server
- HTTP binds to `127.0.0.1` only (localhost)
- No TLS (localhost-only; future: optional TLS)
- Stdio transport available (no network exposure)

### Discord Bot
- Uses Discord's WebSocket + HTTPS API
- Token never sent in logs or error messages

### Webhook Dispatch
- HTTPS only (enforced by `_is_secure_url`)
- Rate limited (SQLite-backed persistent rate limiting)
- Delivery logged for audit

---

## 7. Clipboard Security

- Uploaded clip URLs auto-clear from clipboard after **60 seconds**
- Clipboard only cleared if it still contains the expected URL (avoids clearing user data)
- Copy action logged in `url_history` table

---

## 8. Process Security

### GSR Subprocess
- PID-based signaling (`save-replay.sh` uses `pgrep` + `kill`)
- No broad `killall` commands
- Subprocess managed via `subprocess.Popen` with controlled arguments

### ffmpeg Subprocesses
- Arguments constructed programmatically (no shell injection)
- `subprocess.Popen` with `shell=False` (default)

### File Permissions
- Database: `0o600`
- Desktop file: `0o755`
- Config directory: `0o700` (implied by `os.makedirs` default)

---

## 9. Vulnerability Reporting

Security issues should be reported via the GitHub repository issues or directly to the maintainer. Given the pre-release status, no bounty program is currently available.

---

## 10. Related Documentation

- `TRUTH.md` — aspirational security state and audit findings
- `ARCHITECTURE.md` — encryption architecture diagram
- `CONTRIBUTING.md` — how to contribute securely
