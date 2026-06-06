"""Tests for core/uploader.py — rclone upload with retry logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.uploader import _MAX_RETRIES, _RETRY_DELAYS, Uploader, UploaderError

pytestmark = [pytest.mark.integration]


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
        with patch.dict(
            "os.environ",
            {
                "MOMENT_RCLONE_REMOTE": "prod-r2",
                "MOMENT_RCLONE_BUCKET": "clips-prod",
            },
        ):
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
            patch.object(uploader, "_do_copy"),
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
# Log sanitization
# ---------------------------------------------------------------------------


class TestLogSanitization:
    """Verify that remote/bucket names are not leaked in info-level logs."""

    def test_upload_success_log_sanitized(self, test_path: Path, uploader: Uploader) -> None:
        """Upload success message should show filename only, not remote:bucket/path."""
        with (
            patch.object(uploader, "_do_copy"),
            patch.object(uploader, "_verify_upload", return_value=True),
            patch.object(uploader, "_ensure_rclone"),
            patch("moment.core.uploader.logger") as mock_logger,
        ):
            uploader.upload(test_path)
            # Find the info-level log calls
            info_calls = [
                c for c in mock_logger.info.call_args_list if c[0] and isinstance(c[0][0], str)
            ]
            for call in info_calls:
                msg = call[0][0] % call[0][1:] if len(call[0]) > 1 else call[0][0]
                # Should not contain the remote:bucket prefix
                assert "test-remote:test-bucket" not in str(msg), f"Leaked remote info: {msg}"

    def test_build_url_uses_debug_not_info(self, uploader: Uploader) -> None:
        """_build_url without base_url should log at debug level, not info."""
        with patch("moment.core.uploader.logger") as mock_logger:
            uploader._build_url("foo.mp4")
            # Should not call info
            info_calls = [
                c for c in mock_logger.info.call_args_list if c[0] and "rclone path" in str(c[0])
            ]
            assert len(info_calls) == 0

    def test_do_copy_logs_sanitized(self, uploader: Uploader) -> None:
        """_do_copy should not leak the full rclone command in info/warning/error logs."""
        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.uploader.logger") as mock_logger,
        ):
            mock_run.return_value.returncode = 0
            uploader._do_copy(Path("/tmp/test.mp4"), "test-remote:test-bucket/foo.mp4")
            info_calls = [c for c in mock_logger.info.call_args_list if c[0]]
            for call in info_calls:
                msg = call[0][0] if call[0] else ""
                assert "test-remote:test-bucket" not in str(msg)


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


# ---------------------------------------------------------------------------
# Total deadline (Spec 20)
# ---------------------------------------------------------------------------


class TestDeadline:
    def test_deadline_not_exceeded_for_quick_upload(
        self, test_path: Path, uploader: Uploader
    ) -> None:
        """Quick uploads should not trigger the deadline."""
        with (
            patch.object(uploader, "_do_copy"),
            patch.object(uploader, "_verify_upload", return_value=True),
            patch.object(uploader, "_ensure_rclone"),
        ):
            url = uploader.upload(test_path)
            assert url.startswith("https://")

    def test_deadline_exceeded_raises(self, test_path: Path) -> None:
        """Upload that exceeds deadline should raise UploaderError."""
        from moment.core.uploader import _TOTAL_DEADLINE

        u = Uploader(remote="test", bucket="test")
        with (
            patch.object(u, "_ensure_rclone"),
            patch.object(u, "_do_copy"),
            patch.object(u, "_verify_upload", return_value=True),
            patch("time.monotonic") as mock_mono,
            patch("time.sleep"),
        ):
            # First call returns 0 (start), second returns > deadline
            mock_mono.side_effect = [0.0, _TOTAL_DEADLINE + 1.0]

            with pytest.raises(UploaderError, match="deadline exceeded"):
                u.upload(test_path)

    def test_deadline_checked_each_attempt(self, test_path: Path) -> None:
        """Deadline is checked before each retry, not just at start."""
        from moment.core.uploader import _TOTAL_DEADLINE

        u = Uploader(remote="test", bucket="test")
        with (
            patch.object(u, "_ensure_rclone"),
            patch.object(u, "_do_copy") as mock_copy,
            patch.object(u, "_verify_upload", return_value=False),
            patch("time.monotonic") as mock_mono,
            patch("time.sleep"),
        ):
            # Attempt 0: time=0, Attempt 1: time > deadline
            mock_copy.side_effect = subprocess.CalledProcessError(1, "rclone")
            mock_mono.side_effect = [0.0, _TOTAL_DEADLINE + 1.0]

            with pytest.raises(UploaderError, match="deadline exceeded"):
                u.upload(test_path)


# ---------------------------------------------------------------------------
# Circuit breaker (Spec 20)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def setup_method(self):
        """Reset circuit breaker state before each test."""
        import moment.core.uploader as up_mod

        with up_mod.Uploader._failure_lock:
            up_mod.Uploader._consecutive_failures = 0
            up_mod.Uploader._circuit_open_until = 0.0

    def test_circuit_breaker_opens_after_consecutive_failures(self, test_path: Path) -> None:
        """After 3 consecutive failures, the 4th attempt is blocked."""
        from moment.core.uploader import _CIRCUIT_BREAKER_FAILURES

        u = Uploader(remote="test", bucket="test")

        # First, cause 3 failures to trip the circuit breaker
        for _ in range(_CIRCUIT_BREAKER_FAILURES):
            with (
                patch.object(u, "_ensure_rclone"),
                patch.object(u, "_do_copy", side_effect=subprocess.CalledProcessError(1, "rclone")),
                patch("time.sleep"),
            ):
                with pytest.raises(UploaderError, match="failed after"):
                    u.upload(test_path)

        # Now the 4th attempt should be blocked by circuit breaker
        with (
            patch.object(u, "_ensure_rclone"),
        ):
            with pytest.raises(UploaderError, match="Circuit breaker open"):
                u.upload(test_path)

    def test_circuit_breaker_resets_after_success(self, test_path: Path) -> None:
        """One successful upload resets the circuit breaker."""

        u = Uploader(remote="test", bucket="test")

        # Cause 2 failures (not enough to trip)
        for _ in range(2):
            with (
                patch.object(u, "_ensure_rclone"),
                patch.object(u, "_do_copy", side_effect=subprocess.CalledProcessError(1, "rclone")),
                patch("time.sleep"),
            ):
                with pytest.raises(UploaderError, match="failed after"):
                    u.upload(test_path)

        # Now a successful upload should reset the counter
        with (
            patch.object(u, "_do_copy"),
            patch.object(u, "_verify_upload", return_value=True),
            patch.object(u, "_ensure_rclone"),
        ):
            url = u.upload(test_path)
            assert url.startswith("test:test/")

        # Failures should be reset to 0
        from moment.core.uploader import Uploader as Up

        assert Up._consecutive_failures == 0

    def test_circuit_breaker_is_thread_safe(self, test_path: Path) -> None:
        """Circuit breaker state updates are thread-safe."""
        import concurrent.futures

        import moment.core.uploader as up_mod

        with up_mod.Uploader._failure_lock:
            up_mod.Uploader._consecutive_failures = 0
            up_mod.Uploader._circuit_open_until = 0.0

        def cause_failure() -> None:
            u = Uploader(remote="test", bucket="test")
            with (
                patch.object(u, "_ensure_rclone"),
                patch.object(u, "_do_copy", side_effect=subprocess.CalledProcessError(1, "rclone")),
                patch("moment.core.uploader.time.sleep"),
            ):
                try:
                    u.upload(test_path)
                except UploaderError:
                    pass

        # Run 3 failures in parallel — should increment correctly
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(cause_failure) for _ in range(3)]
            done, not_done = concurrent.futures.wait(futures, timeout=10)
            assert not not_done, "upload threads did not finish"
            for fut in done:
                fut.result()

        # After exactly 3 failures, circuit breaker should be open
        with up_mod.Uploader._failure_lock:
            assert up_mod.Uploader._consecutive_failures >= 3
