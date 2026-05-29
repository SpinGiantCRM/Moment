# Storage Providers

Moment uploads your clips to the cloud so you can share them, free up local disk space, and keep a permanent archive. Behind the scenes it uses [rclone](https://rclone.org/), which supports **40+ storage backends** — you're not locked into any one provider.

## How it works

1. You configure a "remote" in rclone (a name + credentials for your storage)
2. Moment's `Uploader` uses rclone to `copy` your encoded clip to `remote:bucket/path`
3. If you set a `base_url`, Moment generates a shareable link

You pick what fits your budget, privacy, and region. Here are the most popular options.

---

## Quick start for popular providers

### Backblaze B2 (💰 cheapest for stored video)

Backblaze B2 is the most cost-effective choice for large video archives — $0.006/GB/month storage, $0.01/GB egress.

```bash
rclone config
# Select "n" for new remote
# Name: b2
# Type: 4 (b2)
# Account ID: (your B2 application key ID)
# Application Key: (your B2 application key)
# Save

# Test it
rclone mkdir b2:moment-clips
rclone --progress ls b2:moment-clips
```

Add to `~/.config/moment/config.yaml` or your shell profile:

```bash
export MOMENT_RCLONE_REMOTE=b2
export MOMENT_RCLONE_BUCKET=moment-clips
# B2 public URLs require a bucket policy —
# see https://rclone.org/b2/#private-buckets
```

### Cloudflare R2 (🚫 no egress fees)

R2 has zero egress charges — ideal if you share clips frequently. Storage is $0.015/GB/month.

```bash
rclone config
# Select "n" for new remote
# Name: r2
# Type: 43 (s3 compliant)
# Provider: Cloudflare
# Access Key ID: (your R2 token)
# Secret Access Key: (your R2 token secret)
# Region: auto
# Endpoint: https://<accountid>.r2.cloudflarestorage.com
# Leave ACL blank
# Save

# Test it
rclone mkdir r2:moment
rclone cp test.mp4 r2:moment/test.mp4
```

Configure Moment:

```bash
export MOMENT_RCLONE_REMOTE=r2
export MOMENT_RCLONE_BUCKET=moment
export MOMENT_BASE_URL=https://pub-<hash>.r2.dev
```

Your R2 public URL is in the Cloudflare dashboard under R2 → bucket → Settings → Public URL.

### AWS S3 (🌎 most regions)

S3 is available everywhere, with $0.023/GB/month standard storage.

```bash
rclone config
# Type: 43 (s3 compliant)
# Provider: AWS
# Access Key ID: (your IAM key)
# Secret Access Key: (your IAM secret)
# Region: us-east-1 (or your region)
# Save

# Test it
rclone mkdir s3:moment-clips
```

Configure Moment:

```bash
export MOMENT_RCLONE_REMOTE=s3
export MOMENT_RCLONE_BUCKET=moment-clips
export MOMENT_BASE_URL=https://moment-clips.s3.amazonaws.com
```

### Google Cloud Storage

```bash
rclone config
# Type: 11 (google cloud storage)
# Project number: (your GCP project)
# Leave service account blank for auto-detect, or point to a JSON key
# Save

export MOMENT_RCLONE_REMOTE=gcs
export MOMENT_RCLONE_BUCKET=moment-clips
```

### Wasabi (⚡ fast — no egress fees)

Wasabi has no egress fees and $0.0069/GB/month storage (similar to B2).

```bash
rclone config
# Type: 43 (s3 compliant)
# Provider: Wasabi
# Access Key ID: (your Wasabi key)
# Secret Access Key: (your Wasabi secret)
# Region: us-east-1
# Save

export MOMENT_RCLONE_REMOTE=wasabi
export MOMENT_RCLONE_BUCKET=moment-clips
export MOMENT_BASE_URL=https://s3.wasabisys.com/moment-clips
```

### Dropbox / Google Drive (🙂 casual)

For personal use where you don't mind files sitting alongside your docs:

```bash
rclone config
# Type: 8 (dropbox) or 17 (google drive)
# Follow the OAuth flow
# Save

export MOMENT_RCLONE_REMOTE=dropbox
export MOMENT_RCLONE_BUCKET=   # leave blank for root
```

### Self-hosted MinIO (🏠 full control)

Run your own S3-compatible server:

```bash
rclone config
# Type: 43 (s3 compliant)
# Provider: Other
# Endpoint: http://10.0.0.5:9000
# Access Key ID: (your minio key)
# Secret Access Key: (your minio secret)
# Region: us-east-1
# Save

export MOMENT_RCLONE_REMOTE=minio
export MOMENT_RCLONE_BUCKET=moment
```

### SFTP / local NAS (🔒 no cloud at all)

Upload to your own server or NAS over SSH:

```bash
rclone config
# Type: 32 (sftp)
# Host: 10.0.0.5
# User: chasem
# Key File: ~/.ssh/id_ed25519
# Save

export MOMENT_RCLONE_REMOTE=nas
export MOMENT_RCLONE_BUCKET=   # leave empty
```

---

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `MOMENT_RCLONE_REMOTE` | `r2` | rclone remote name |
| `MOMENT_RCLONE_BUCKET` | `moment` | bucket/container on the remote |
| `MOMENT_BASE_URL` | (none) | public URL prefix for shareable links |

Add these to `~/.profile`, `~/.bashrc`, or your desktop environment's session config.

### Config file (future)

A storage configuration UI in the Settings dialog is on the roadmap. For now, use the env vars above.

---

## Verifying your setup

```bash
# List what's on your remote
rclone ls $MOMENT_RCLONE_REMOTE:$MOMENT_RCLONE_BUCKET

# Upload a test
echo "hello" > /tmp/test-moment.txt
rclone copy /tmp/test-moment.txt $MOMENT_RCLONE_REMOTE:$MOMENT_RCLONE_BUCKET/

# Launch Moment and check the Stats page
moment
```

If the upload bar on the Stats page starts moving, everything's wired.

---

## FAQ

**Do I need a public URL?** No. If you only use Moment to archive clips locally and want cloud backup without sharing, leave `MOMENT_BASE_URL` unset. The clip will upload but won't have a shareable link.

**Can I use multiple remotes?** One at a time for now. Swap the env var to switch. Multi-remote support is on the roadmap.

**What about retention?** Moment manages a local FIFO — old local clips are auto-deleted when disk usage exceeds your configured limit. The cloud copy is permanent (you can delete from within Moment's UI).

**Is this secure?** rclone credentials live in `~/.config/rclone/rclone.conf` — keep that file safe (600 permissions). The upload channel is always encrypted (HTTPS/SSH).

**I don't see my provider** — rclone supports 40+ backends. Run `rclone config` to see them all. If yours isn't listed above, just follow rclone's setup and point Moment's env vars at it.

---

## Further reading

- [rclone docs](https://rclone.org/docs/)
- [rclone backend list](https://rclone.org/overview/)
- [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing)
- [Cloudflare R2 pricing](https://www.cloudflare.com/products/r2/)
