# Database Schema

**Engine:** SQLite 3 (WAL mode) via sqlcipher3 (AES-256 encrypted) — encryption is mandatory, no plaintext fallback
**Location:** `~/.config/moment/clips.db`
**Permissions:** `0o600` (owner read/write)
**Tables:** 16

---

## Table: `schema_version`

Migration tracking table. Used by `run_migrations()` in `repositories/base.py` to apply pending migrations sequentially inside transactions.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `version` | TEXT PK | — | Migration identifier (e.g., `"001_initial"`) |
| `applied_at` | TEXT | `datetime('now')` | When the migration was applied |

---

## Table: `clips`

The primary data table. One row per captured clip.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `stem` | TEXT | '' | Human-readable identifier (e.g., "cs2-2026-05-01-12-00") |
| `source_path` | TEXT | '' | Path to raw MKV from GSR |
| `encoded_path` | TEXT | NULL | Path to encoded MP4 |
| `thumb_path` | TEXT | NULL | Path to thumbnail JPEG |
| `recorded_at` | TEXT | `datetime('now')` | ISO 8601 timestamp of capture |
| `duration` | REAL | 0 | Duration in seconds |
| `file_size` | INTEGER | 0 | File size in bytes |
| `video_codec` | TEXT | '' | Source codec (h264, hevc, etc.) |
| `fps` | REAL | 0 | Frames per second |
| `resolution` | TEXT | `[0,0]` | JSON array `[width, height]` |
| `has_mic_audio` | INTEGER | 0 | Boolean: microphone audio present |
| `has_game_audio` | INTEGER | 0 | Boolean: game audio present |
| `title` | TEXT | '' | User-editable title |
| `game` | TEXT | NULL | Game name |
| `folder` | TEXT | NULL | Folder name |
| `favorite` | INTEGER | 0 | Boolean: favorited |
| `status` | TEXT | PENDING | Pipeline status (PENDING, ENCODING, DONE, UPLOADING, UPLOADED, ERROR, CORRUPT) |
| `error_message` | TEXT | NULL | Error details on failure |
| `uploaded_at` | TEXT | NULL | ISO 8601 upload timestamp |
| `r2_url` | TEXT | NULL | Public cloud URL |
| `r2_path` | TEXT | NULL | Cloud storage path |
| `copy_count` | INTEGER | 0 | URL copy count |
| `visibility` | TEXT | 'public' | Visibility level |
| `created_at` | TEXT | `datetime('now')` | Row creation timestamp |
| `deleted_at` | TEXT | NULL | Soft-delete timestamp |
| `protect_from_retention` | INTEGER | 0 | Exclude from auto-deletion |
| `clip_type` | TEXT | 'VIDEO' | VIDEO, SCREENSHOT, IMPORTED |
| `source_app` | TEXT | NULL | Application that created the clip |
| `original_filename` | TEXT | NULL | Original filename (imported clips) |
| `updated_at` | TEXT | `datetime('now')` | Last update timestamp |
| `watched_at` | TEXT | NULL | Last playback timestamp |
| `watch_count` | INTEGER | 0 | Playback count |
| `discord_user_id` | TEXT | '' | Discord user ID for ownership |

**Indexes:** stem, game, folder, status, deleted_at, created_at

---

## Table: `tags`

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `name` | TEXT UNIQUE | — | Tag name |
| `color` | TEXT | NULL | Optional hex color |
| `created_at` | TEXT | `datetime('now')` | Creation timestamp |

---

## Table: `clip_tags`

Many-to-many relationship between clips and tags.

| Column | Type | Description |
|--------|------|-------------|
| `clip_id` | TEXT (FK → clips.id) | Clip UUID |
| `tag_id` | TEXT (FK → tags.id) | Tag UUID |

**Primary Key:** (clip_id, tag_id)

---

## Table: `edit_profiles`

One-to-one with clips. Stores editing metadata.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `clip_id` | TEXT PK (FK → clips.id) | — | Clip UUID |
| `trim_start` | REAL | NULL | Trim start in seconds |
| `trim_end` | REAL | NULL | Trim end in seconds |
| `split_points` | TEXT | `[]` | JSON array of split timestamps |
| `segments` | TEXT | `[]` | JSON array of SegmentEdit |
| `game_audio_volume` | REAL | 1.0 | 0.0–2.0 |
| `mic_audio_volume` | REAL | 1.0 | 0.0–2.0 |
| `filters` | TEXT | `[]` | JSON array of FilterConfig |
| `overlays` | TEXT | `[]` | JSON array of OverlayConfig |
| `merge_source_ids` | TEXT | NULL | JSON array of merged clip IDs |
| `edit_version` | INTEGER | 1 | Version counter |

---

## Table: `bookmarks`

Session bookmark markers for mid-capture navigation.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `session_stem` | TEXT | — | Session identifier |
| `offset_seconds` | REAL | — | Offset in session |
| `created_at` | TEXT | `datetime('now')` | Creation timestamp |
| `label` | TEXT | NULL | Optional label |

**Index:** session_stem

---

## Table: `webhooks`

Discord webhook configurations. URLs are encrypted with Fernet.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `url` | TEXT | — | Encrypted webhook URL |
| `name` | TEXT | '' | Human-readable name |
| `enabled` | INTEGER | 1 | Boolean |
| `notify_on` | TEXT | `[]` | JSON array of event types |
| `per_game_filter` | TEXT | NULL | JSON array of game names (whitelist) |
| `include_clip_url` | INTEGER | 0 | Include R2 URL in embed |

---

## Table: `webhook_log`

Delivery history for webhook dispatches.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `webhook_id` | TEXT (FK → webhooks.id) | — | Webhook UUID |
| `clip_id` | TEXT (FK → clips.id) | — | Clip UUID |
| `delivered_at` | TEXT | `datetime('now')` | Delivery timestamp |
| `success` | INTEGER | 1 | Boolean |
| `status_code` | INTEGER | 200 | HTTP response code |
| `error_message` | TEXT | NULL | Error details on failure |

---

## Table: `folders`

User-defined clip folders.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `name` | TEXT UNIQUE | — | Folder name |
| `created_at` | TEXT | `datetime('now')` | Creation timestamp |

---

## Table: `folder_clips`

Many-to-many relationship between folders and clips.

| Column | Type | Description |
|--------|------|-------------|
| `folder_id` | TEXT (FK → folders.id) | Folder UUID |
| `clip_id` | TEXT (FK → clips.id) | Clip UUID |

**Primary Key:** (folder_id, clip_id)

---

## Table: `game_profiles`

Per-game recording and encoding configuration.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `game_name` | TEXT UNIQUE | — | Game process name (e.g., "cs2") |
| `display_name` | TEXT | — | Human-readable name (e.g., "Counter-Strike 2") |
| `replay_duration` | INTEGER | 30 | Replay buffer duration in seconds |
| `audio_config` | TEXT | NULL | JSON audio configuration |
| `capture_fps` | INTEGER | 60 | Capture FPS |
| `encode_timing` | TEXT | NULL | Encode timing strategy |
| `quality_preset` | TEXT | NULL | Quality preset override |
| `pause_encode` | INTEGER | 1 | Pause encoding during gameplay |
| `pause_thumbnail` | INTEGER | 1 | Pause thumbnail during gameplay |
| `auto_tag` | INTEGER | 1 | Auto-tag clips with game name |
| `auto_open_editor` | INTEGER | 1 | Auto-open editor on game exit |
| `review_card` | TEXT | NULL | JSON ReviewCardConfig |
| `min_duration` | INTEGER | 30 | Minimum clip duration to keep on game exit |
| `post_capture_action` | TEXT | 'card' | Action on game exit: card, discard, editor |

**Index:** game_name

---

## Table: `tasks`

Pipeline task persistence for durability across restarts.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `type` | TEXT | — | Task kind (encode, upload, thumbnail, import, health_check) |
| `priority` | INTEGER | 0 | Higher = more urgent |
| `payload` | TEXT | `{}` | JSON task parameters |
| `status` | TEXT | PENDING | PENDING, RUNNING, COMPLETED, FAILED, CANCELLED |
| `created_at` | TEXT | `datetime('now')` | Creation timestamp |
| `retry_count` | INTEGER | 0 | Current retry attempt |
| `max_retries` | INTEGER | 3 | Maximum retry attempts |
| `error_message` | TEXT | NULL | Error details on failure |

**Index:** status

---

## Table: `url_history`

Audit trail of URL copy operations.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `clip_id` | TEXT (FK → clips.id) | — | Clip UUID |
| `url` | TEXT | — | Copied URL |
| `copied_at` | TEXT | `datetime('now')` | Copy timestamp |

**Index:** clip_id

---

## Table: `rate_limits`

Persistent rate limiting for Discord bot and webhook dispatch.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `key` | TEXT PK | — | Rate limit key |
| `last_called` | REAL | — | Unix timestamp of last call |
| `expires_at` | REAL | — | Expiration timestamp for auto-cleanup |

**Index:** expires_at

---

## Table: `pip_cache`

Cache for picture-in-picture window segments.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT PK | — | UUID v4 |
| `clip_id` | TEXT (FK → clips.id) | — | Clip UUID |
| `start_offset` | REAL | 0.0 | Start offset in seconds |
| `end_offset` | REAL | 30.0 | End offset in seconds |
| `created_at` | TEXT | `datetime('now')` | Creation timestamp |
| `expires_at` | TEXT | NULL | Expiration timestamp |

**Index:** clip_id

---

## Table: `settings`

Generic key-value configuration store.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `key` | TEXT PK | — | Setting name |
| `value` | TEXT | '' | JSON-encoded setting value |

---

## Migration Framework

**Location:** `src/moment/core/repositories/base.py`

Moment uses a numbered migration framework with a `schema_version` table. `run_migrations()` applies pending migrations sequentially inside transactions.

### The `_MIGRATIONS` List

```python
_MIGRATIONS: list[tuple[str, _MigrationFunc]] = [
    ("001_initial", _migration_001_initial),
    ("002_webhook_include_url", _migration_002_webhook_include_url),
    ("003_webhook_per_game_filter", _migration_003_webhook_per_game_filter),
    ("004_migrate_secrets_to_keyring", _migration_004_migrate_secrets_to_keyring),
    ("005_migrate_webhook_key_to_keyring", _migration_005_migrate_webhook_key_to_keyring),
]
```

### Migration Function Pattern

Each migration is a module-level function accepting `sqlite3.Connection`:

```python
def _migration_002_webhook_include_url(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(webhooks)").fetchall()
    columns = {r["name"] for r in rows}
    if "include_clip_url" not in columns:
        conn.execute(
            "ALTER TABLE webhooks ADD COLUMN include_clip_url INTEGER NOT NULL DEFAULT 0"
        )
```

All columns added by migrations also exist in `SCHEMA_SQL` for fresh installs, so migrations are idempotent — they check `PRAGMA table_info` before applying `ALTER TABLE`.

### When adding a new column

1. Add the column to `SCHEMA_SQL` (for fresh installs)
2. Create a migration function in `base.py` that accepts `sqlite3.Connection` and checks `PRAGMA table_info`
3. Append `(f"{NNN}_name", _migration_NNN_name)` to the `_MIGRATIONS` list
4. `run_migrations()` handles execution order automatically

### When adding a new table

1. Add the `CREATE TABLE` statement to `SCHEMA_SQL`
2. No migration needed for brand new tables — they exist at schema creation
