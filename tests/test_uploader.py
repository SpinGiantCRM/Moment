"""Tests for core/uploader.py — rclone upload with retry logic."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.uploader import Uploader, UploaderError, _RETRY_DELAYS, _MAX_RETRIES


@pytest.fixture
def test_path() -> Path:
    return Path("/tmp/test_upload_clip.mp4")


@pytest.fixture
def uploader() -> Uploader:
    return Uploader(remote="test-remote", bucket="test-bucket", base_url="https://cdn.example.com")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_remote_and_bucket(self) -> None:
        u = Uploader(remote="my-r2", bucket="my-bucket")
        assert u.remote == "my-r2"
        assert u.bucket == "my-bucket"

    def test_base_url(self) -> None:
        u = Uploader(base_url="https://cdn.example.com")
        assert u.base_url == "https://cdn.example.com"

    def test_base_url_trailing_slash_stripped(self) -> None:
        u = Uploader(base_url="https://cdn.example.com/")
        assert u.base_url == "https://cdn.example.com"

    def test_default_remote(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            u = Uploader()
            assert u.remote == "r2"

    def test_env_override(self) -> None:
        with patch.dict("os.environ", {
            "MOMENT_RCLONE_REMOTE": "prod-r2",
            "MOMENT_RCLONE_BUCKET": "clips-prod",
        }):
            u = Uploader()
            assert u.remote == "prod-r2"
            assert u.bucket == "clips-prod"


# ---------------------------------------------------------------------------
# Upload (mocked rclone)
# ---------------------------------------------------------------------------

class TestUpload:
    def test_successful_upload(self, test_path: Path, uploader: Uploader) -> None:
        with (
            patch.object(uploader, "_do_copy") as mock_copy,
            patch.object(uploader, "_verify_upload", return_value=True),
            patch.object(uploader, "_ensure_rclone"),
        ):
            url = uploader.upload(test_path)

            mock_copy.assert_called_once()
            assert url.startswith("https://cdn.example.com/")
            assert test_path.name in url

    def test_upload_with_custom_remote_path(self, test_path: Path, uploader: Uploader) -> None:
        with (
            patch.object(uploader, "_do_copy") as mock_copy,
            patch.object(uploader, "_verify_upload", return_value=True),
            patch.object(uploader, "_ensure_rclone"),
        ):
            url = uploader.upload(test_path, remote_path="custom/path.mp4")
            assert "custom/path.mp4" in url

    def test_upload_retries_on_failure(self, test_path: Path, uploader: Uploader) -> None:
        """Should retry _MAX_RETRIES times before raising."""
        with (
            patch.object(uploader, "_do_copy") as mock_copy,
            patch.object(uploader, "_ensure_rclone"),
            patch("time.sleep"),  # Don't actually sleep during retries
        ):
            mock_copy.side_effect = subprocess.CalledProcessError(1, "rclone")

            with pytest.raises(UploaderError, match="failed after"):
                uploader.upload(test_path)

            assert mock_copy.call_count == _MAX_RETRIES + 1

    def test_upload_retries_verification_failure(self, test_path: Path, uploader: Uploader) -> None:
        with (
            patch.object(uploader, "_do_copy"),
            patch.object(uploader, "_verify_upload", return_value=False),
            patch.object(uploader, "_ensure_rclone"),
            patch("time.sleep"),  # Don't actually sleep during retries
        ):
            with pytest.raises(UploaderError, match="failed after"):
                uploader.upload(test_path)

    def test_upload_succeeds_after_retry(self, test_path: Path, uploader: Uploader) -> None:
        """Verify succeeds after one failure."""
        with (
            patch.object(uploader, "_do_copy") as mock_copy,
            patch.object(uploader, "_verify_upload") as mock_verify,
            patch.object(uploader, "_ensure_rclone"),
            patch("time.sleep"),  # Don't actually sleep
        ):
            # First call: copy succeeds, verify fails → retry
            # Second call: both succeed
            mock_verify.side_effect = [False, True]

            url = uploader.upload(test_path)
            assert mock_copy.call_count == 2
            assert url.startswith("https://")

    def test_upload_no_base_url(self, test_path: Path) -> None:
        u = Uploader(remote="r2", bucket="clips")
        with (
            patch.object(u, "_do_copy"),
            patch.object(u, "_verify_upload", return_value=True),
            patch.object(u, "_ensure_rclone"),
        ):
            url = u.upload(test_path)
            assert url.startswith("r2:clips/")


# ---------------------------------------------------------------------------
# Re-upload
# ---------------------------------------------------------------------------

class TestReUpload:
    def test_deletes_then_uploads(self, test_path: Path, uploader: Uploader) -> None:
        with (
            patch("subprocess.run") as mock_run,
            patch.object(uploader, "upload") as mock_upload,
            patch.object(uploader, "_ensure_rclone"),
        ):
            mock_run.return_value.returncode = 0
            mock_upload.return_value = "https://cdn.example.com/new.mp4"

            url = uploader.re_upload(test_path, "old/path.mp4")

            # rclone delete was called
            delete_call = mock_run.call_args_list[0]
            assert "delete" in delete_call[0][0]
            # upload was called with the same remote_path
            mock_upload.assert_called_once_with(test_path, remote_path="old/path.mp4")
            assert url == "https://cdn.example.com/new.mp4"

    def test_reupload_handles_missing_remote(self, test_path: Path, uploader: Uploader) -> None:
        with (
            patch("subprocess.run") as mock_run,
            patch.object(uploader, "upload", return_value="https://cdn.example.com/new.mp4"),
            patch.object(uploader, "_ensure_rclone"),
        ):
            # CalledProcessError from a mocked subprocess.run has stderr=None by default
            error = subprocess.CalledProcessError(1, "rclone")
            error.stderr = "file not found"  # Patch stderr to avoid NoneType.strip() crash
            mock_run.side_effect = error

            # Should not raise — just warn and proceed with upload
            url = uploader.re_upload(test_path, "missing.mp4")
            assert url == "https://cdn.example.com/new.mp4"


# ---------------------------------------------------------------------------
# Rclone availability
# ---------------------------------------------------------------------------

class TestRcloneAvailability:
    def test_missing_rclone_raises(self, test_path: Path) -> None:
        u = Uploader(remote="r2", bucket="clips")
        with (
            patch("shutil.which", return_value=None),
            patch("time.sleep"),  # Don't actually sleep during retries
        ):
            with pytest.raises(UploaderError, match="failed after"):
                u.upload(test_path)

    def test_rclone_present_does_not_raise(self, test_path: Path) -> None:
        u = Uploader(remote="r2", bucket="clips")
        with (
            patch("shutil.which", return_value="/usr/bin/rclone"),
            patch.object(u, "_do_copy"),
            patch.object(u, "_verify_upload", return_value=True),
        ):
            # Should not raise about rclone
            result = u.upload(test_path)
            assert result.startswith("r2:clips/")


# ---------------------------------------------------------------------------
# Retry config
# ---------------------------------------------------------------------------

class TestRetryConfig:
    def test_retry_delays_values(self) -> None:
        """Check the expected exponential backoff values."""
        assert _RETRY_DELAYS == [5.0, 30.0, 300.0]
        assert _MAX_RETRIES == 3

    def test_retry_delays_are_increasing(self) -> None:
        for i in range(1, len(_RETRY_DELAYS)):
            assert _RETRY_DELAYS[i] > _RETRY_DELAYS[i - 1]
