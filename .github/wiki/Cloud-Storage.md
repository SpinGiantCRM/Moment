# Cloud Storage

Moment uploads clips to any of 40+ storage providers via [rclone](https://rclone.org/). No vendor lock-in — pick what fits your budget and region.

## How it works

1. Configure a "remote" in rclone (a name + credentials for your storage)
2. Moment's uploader uses rclone to `copy` encoded clips to `remote:bucket/path`
3. If you set a `base_url`, Moment generates shareable links

## Quick start

### 1. Configure rclone

```bash
rclone config
```

Follow the interactive setup for your provider (see below for common ones).

### 2. Set environment variables

Add to `~/.profile`, `~/.bashrc`, or your DE session config:

```bash
export MOMENT_RCLONE_REMOTE=r2       # your remote name
export MOMENT_RCLONE_BUCKET=moment   # your bucket/container
export MOMENT_BASE_URL=https://pub-xxxx.r2.dev  # optional, for share links
```

### 3. Verify

```bash
rclone ls $MOMENT_RCLONE_REMOTE:$MOMENT_RCLONE_BUCKET
moment  # launch and check the Status page
```

## Popular providers

### Backblaze B2 — cheapest for large archives

Storage: $0.006/GB/month · Egress: $0.01/GB

```bash
rclone config
# New remote → name: b2 → type: 4 (b2)
# Account ID: (your B2 application key ID)
# Application Key: (your B2 application key)
```

```bash
export MOMENT_RCLONE_REMOTE=b2
export MOMENT_RCLONE_BUCKET=moment-clips
```

### Cloudflare R2 — no egress fees

Storage: $0.015/GB/month · Egress: $0.00

```bash
rclone config
# New remote → name: r2 → type: 43 (s3 compliant)
# Provider: Cloudflare
# Access Key ID: (your R2 token)
# Secret Access Key: (your R2 token secret)
# Region: auto
# Endpoint: https://<accountid>.r2.cloudflarestorage.com
```

```bash
export MOMENT_RCLONE_REMOTE=r2
export MOMENT_RCLONE_BUCKET=moment
export MOMENT_BASE_URL=https://pub-<hash>.r2.dev
```

### AWS S3 — most regions

Storage: $0.023/GB/month

```bash
rclone config
# New remote → type: 43 (s3 compliant) → Provider: AWS
# Access Key ID / Secret Access Key: (your IAM key)
# Region: us-east-1
```

```bash
export MOMENT_RCLONE_REMOTE=s3
export MOMENT_RCLONE_BUCKET=moment-clips
export MOMENT_BASE_URL=https://moment-clips.s3.amazonaws.com
```

### Wasabi — fast, no egress

Storage: $0.0069/GB/month · Egress: $0.00

```bash
rclone config
# New remote → type: 43 (s3 compliant) → Provider: Wasabi
# Access Key ID / Secret Access Key
# Region: us-east-1
```

```bash
export MOMENT_RCLONE_REMOTE=wasabi
export MOMENT_RCLONE_BUCKET=moment-clips
```

### Google Cloud Storage

```bash
rclone config
# New remote → type: 11 (google cloud storage)
# Project number: (your GCP project)
# Service account key: (path to JSON key, or auto-detect)
```

```bash
export MOMENT_RCLONE_REMOTE=gcs
export MOMENT_RCLONE_BUCKET=moment-clips
```

### Dropbox / Google Drive — casual use

```bash
rclone config
# type: 8 (dropbox) or 17 (google drive)
# Follow OAuth flow
```

```bash
export MOMENT_RCLONE_REMOTE=dropbox
export MOMENT_RCLONE_BUCKET=  # leave blank for root
```

### Self-hosted MinIO — full control

```bash
rclone config
# New remote → type: 43 (s3 compliant) → Provider: Other
# Endpoint: http://10.0.0.5:9000
# Access Key ID / Secret Access Key
# Region: us-east-1
```

```bash
export MOMENT_RCLONE_REMOTE=minio
export MOMENT_RCLONE_BUCKET=moment
```

### SFTP / local NAS — no cloud

```bash
rclone config
# New remote → type: 32 (sftp)
# Host: 10.0.0.5
# User: chasem
# Key File: ~/.ssh/id_ed25519
```

```bash
export MOMENT_RCLONE_REMOTE=nas
export MOMENT_RCLONE_BUCKET=  # leave empty for home dir
```

## Shareable links

Set `MOMENT_BASE_URL` to a public URL prefix. Moment appends the clip path:

```
Share: https://pub-xxxx.r2.dev/2026-05-29/clip-30s.mp4
```

Without `BASE_URL`, the clip still uploads but no shareable link is shown.

## FAQ

**Do I need cloud storage?** No. Clips are stored locally. Upload is optional.

**Can I use multiple remotes?** One at a time for now. Change the env var to switch.

**Is upload automatic?** Yes — clips are uploaded after encoding. You can disable per-clip in the UI.

**What about retention?** Local clips are auto-deleted when disk exceeds your limit. Cloud copies persist until you delete them.
