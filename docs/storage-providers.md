# Storage Providers

Moment uses [rclone](https://rclone.org) for cloud storage upload. This means any of the **40+ rclone backends** are supported.

## Supported Providers

| Provider | rclone Remote Name | Notes |
|----------|-------------------|-------|
| Backblaze B2 | `b2` | Recommended — cheap egress |
| Cloudflare R2 | `r2` | Recommended — no egress fees |
| AWS S3 | `s3` | Standard S3 |
| Google Cloud Storage | `gcs` | |
| Wasabi | `wasabi` | Hot storage |
| DigitalOcean Spaces | `s3` (DO endpoint) | S3-compatible |
| MinIO | `s3` (self-hosted) | S3-compatible |
| Dropbox | `dropbox` | |
| Google Drive | `drive` | |
| OneDrive | `onedrive` | |
| Nextcloud | `nextcloud` | Self-hosted |
| SFTP | `sftp` | Self-hosted / NAS |
| SMB / CIFS | `smb` | Network shares |
| WebDAV | `webdav` | Generic WebDAV |
| Local filesystem | `local` | For testing |

## Configuration

### 1. Install rclone

```bash
# Arch
sudo pacman -S rclone

# Ubuntu/Debian
sudo apt install rclone

# Or install via script
curl https://rclone.org/install.sh | bash
```

### 2. Configure a Remote

```bash
rclone config
```

Follow the interactive prompts to set up your provider. For most providers you'll need:
- Access key / Client ID
- Secret key / Client secret
- Endpoint URL (for S3-compatible providers)
- Region

### 3. Configure Moment

In Moment Settings → Upload tab:
1. Set **Remote name** to the name you chose in rclone (e.g., `r2`)
2. Set **Bucket/path** to your storage path (e.g., `moment`)
3. Set **Base URL** to the public URL for your bucket (e.g., `https://moment.r2.cloudflarestorage.com`)

Or via environment variables:

```bash
export MOMENT_RCLONE_REMOTE=r2
export MOMENT_RCLONE_BUCKET=moment/clips
export MOMENT_BASE_URL=https://clips.example.com
```

## Recommended Setup

### Cloudflare R2 (Free Tier)

```bash
rclone config
> n) New remote
> name: r2
> Storage: s3
> provider: Cloudflare
> access_key_id: <your-key>
> secret_access_key: <your-secret>
> endpoint: https://<account-id>.r2.cloudflarestorage.com
```

Configure Moment: `r2`, bucket `moment`, base URL from R2 public bucket settings.

### Backblaze B2

```bash
rclone config
> name: b2
> Storage: b2
> account: <your-key-id>
> key: <your-application-key>
```

Configure Moment: `b2`, bucket `moment-clips`, base URL from B2 bucket settings.

## Troubleshooting

### "rclone not found"
Install rclone and ensure it's in your `PATH`.

### "Upload failed: Permission denied"
Check your rclone remote credentials and bucket permissions.

### "Invalid bucket name"
Bucket names must follow your provider's naming conventions (usually lowercase, no spaces).

### Rate limiting
Some providers (especially free tiers) enforce upload rate limits. Moment's pipeline handles retries with exponential backoff.
