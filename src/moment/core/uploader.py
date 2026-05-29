"""Uploader — rclone-backed upload to any storage provider.

Uploads encoded clips to any of 40+ cloud storage providers via ``rclone``:
Backblaze B2, Cloudflare R2, AWS S3, Google Cloud Storage, Wasabi, Dropbox,
self-hosted MinIO, and many more. No vendor lock-in.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess  # nosec B404 — required for external tool invocation
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

# Retry configuration
_RETRY_DELAYS: list[float] = [5.0, 30.0, 300.0]  # seconds
_MAX_RETRIES = len(_RETRY_DELAYS)


class UploaderError(RuntimeError):
    """Raised when an upload fails after all retry attempts."""


class Uploader:
    """Uploads clips to any rclone-backed remote (S3, B2, R2, GCS, …)."""

    def __init__(
        self,
        remote: str | None = None,
        bucket: str | None = None,
        *,
        base_url: str | None = None,
        config: Config | None = None,
    ) -> None:
        """Args:
            remote: rclone remote name (e.g. ``"b2"``, ``"r2"``, ``"s3"``).
                Defaults to Config override, then env var, then ``"r2"``.
            bucket: Bucket/container name on the remote.
                Defaults to Config override, then env var, then ``"moment"``.
            base_url: Public base URL for constructing shareable links.
                Defaults to Config override, then env var.
            config: Optional Config instance for path overrides.
        """
        # Config override > explicit arg > env var > hardcoded default
        def _cfg_path(key: str) -> str | None:
            return config.get_path(key) if config is not None else None

        self._remote = (
            remote or _cfg_path("rclone_remote")
            or _env("MOMENT_RCLONE_REMOTE", "r2")
        )
        self._bucket = (
            bucket or _cfg_path("rclone_bucket")
            or _env("MOMENT_RCLONE_BUCKET", "moment")
        )
        self._base_url = (
            base_url or _cfg_path("base_url")
            or _env("MOMENT_BASE_URL", "")
        ).rstrip("/")

        # Lazily check rclone availability
        self._rclone_path: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload(self, path: Path, *, remote_path: str | None = None) -> str:
        """Upload *path* to the configured remote and return its public URL.

        Retries up to 3 times with exponential backoff.

        Args:
            path: Local file to upload.
            remote_path: Optional remote sub-path within the bucket.
                Defaults to the file name.

        Returns:
            The public URL of the uploaded file.

        Raises:
            UploaderError: If the upload fails after all retries.
        """
        dest = f"{self._remote}:{self._bucket}/{remote_path or path.name}"
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                self._ensure_rclone()
                self._do_copy(path, dest)
                if self._verify_upload(dest):
                    url = self._build_url(remote_path or path.name)
                    logger.info("Uploaded %s → %s", path.name, url)
                    return url
                msg = f"Upload verification failed for {dest} (attempt {attempt + 1})"
                logger.warning(msg)
                last_error = UploaderError(msg)
            except (subprocess.CalledProcessError, UploaderError) as exc:
                last_error = exc
                logger.warning(
                    "Upload attempt %d/%d failed: %s",
                    attempt + 1, _MAX_RETRIES + 1, exc,
                )

            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                logger.info("Retrying upload in %.0fs …", delay)
                time.sleep(delay)

        raise UploaderError(f"Upload failed after {_MAX_RETRIES + 1} attempts") from last_error

    def re_upload(self, path: Path, existing_remote_path: str) -> str:
        """Delete the existing remote file then upload the new one.

        Args:
            path: New local file.
            existing_remote_path: The remote path to replace.

        Returns:
            Public URL of the newly uploaded file.
        """
        self._ensure_rclone()
        dest = f"{self._remote}:{self._bucket}/{existing_remote_path}"
        try:
            subprocess.run(
                ["rclone", "delete", dest],
                capture_output=True,
                text=True,
                check=True,
            )  # nosec
            logger.info("Deleted old remote file: %s", dest)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Could not delete old remote file (may not exist): %s",
                exc.stderr.strip(),
            )

        return self.upload(path, remote_path=existing_remote_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _do_copy(self, path: Path, dest: str) -> None:
        """Execute ``rclone copy``."""
        cmd = ["rclone", "copy", str(path), dest, "--progress"]
        logger.debug("Running: %s", cmd)
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)  # nosec B603 — tokenized args, no shell=True

    def _verify_upload(self, dest: str) -> bool:
        """Check that the file exists on the remote."""
        try:
            result = subprocess.run(
                ["rclone", "lsf", dest],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )  # nosec
            return result.stdout.strip() != ""
        except subprocess.CalledProcessError:
            return False

    def _build_url(self, remote_path: str) -> str:
        """Construct the public URL from the base URL and remote path."""
        if self._base_url:
            return f"{self._base_url}/{remote_path.lstrip('/')}"
        dest = f"{self._remote}:{self._bucket}/{remote_path}"
        logger.info("No base_url set — returning rclone path %s", dest)
        return dest

    def _ensure_rclone(self) -> None:
        """Verify rclone is available; raise early if not."""
        if self._rclone_path is None:
            self._rclone_path = shutil.which("rclone")
            if self._rclone_path is None:
                raise UploaderError("rclone not found on system PATH")

    @property
    def remote(self) -> str:
        return self._remote

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def base_url(self) -> str:
        return self._base_url


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)
