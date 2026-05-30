"""Tests for utils/subprocess.py — sandboxed subprocess helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from moment.utils.subprocess import (
    _FD_CLOSE_MAX,
    Popen_sandboxed,
    _sandbox_preexec,
    _try_qprocess,
    run_sandboxed,
)


class TestSandboxPreexec:
    def test_setsid_called(self) -> None:
        """_sandbox_preexec calls os.setsid()."""
        with patch("moment.utils.subprocess.os.setsid") as mock_setsid, \
             patch("moment.utils.subprocess.os.getuid", return_value=1000), \
             patch("moment.utils.subprocess.os.closerange"):
            _sandbox_preexec()
            mock_setsid.assert_called_once()

    def test_setsid_graceful_failure(self) -> None:
        """_sandbox_preexec doesn't raise on setsid OSError."""
        with patch("moment.utils.subprocess.os.setsid", side_effect=OSError), \
             patch("moment.utils.subprocess.os.getuid", return_value=1000), \
             patch("moment.utils.subprocess.os.closerange"):
            # Should not raise
            _sandbox_preexec()

    def test_drops_root_privileges(self) -> None:
        """When uid==0, call setgid/setuid to drop privileges."""
        with patch("moment.utils.subprocess.os.setsid"), \
             patch("moment.utils.subprocess.os.getuid", return_value=0), \
             patch("moment.utils.subprocess.os.getgid", return_value=1000), \
             patch("moment.utils.subprocess.os.closerange"), \
             patch("moment.utils.subprocess.os.setgid") as mock_setgid, \
             patch("moment.utils.subprocess.os.setuid") as mock_setuid:
            _sandbox_preexec()
            mock_setgid.assert_called_once()
            mock_setuid.assert_called_once()

    def test_no_privilege_drop_for_normal_user(self) -> None:
        """Normal user (uid!=0) doesn't trigger setgid/setuid."""
        with patch("moment.utils.subprocess.os.setsid"), \
             patch("moment.utils.subprocess.os.getuid", return_value=1000), \
             patch("moment.utils.subprocess.os.closerange"), \
             patch("moment.utils.subprocess.os.setgid") as mock_setgid, \
             patch("moment.utils.subprocess.os.setuid") as mock_setuid:
            _sandbox_preexec()
            mock_setgid.assert_not_called()
            mock_setuid.assert_not_called()

    def test_closerange_called(self) -> None:
        """_sandbox_preexec closes FDs 3.._FD_CLOSE_MAX."""
        with patch("moment.utils.subprocess.os.setsid"), \
             patch("moment.utils.subprocess.os.getuid", return_value=1000), \
             patch("moment.utils.subprocess.os.closerange") as mock_close:
            _sandbox_preexec()
            mock_close.assert_called_once_with(3, _FD_CLOSE_MAX)


class TestRunSandboxed:
    def test_adds_preexec_fn(self) -> None:
        """run_sandboxed adds _sandbox_preexec as preexec_fn."""
        mock_result = subprocess.CompletedProcess(
            args=["echo", "hi"], returncode=0, stdout="hi\n", stderr=""
        )
        with patch("moment.utils.subprocess._try_qprocess", return_value=None), \
             patch("moment.utils.subprocess.subprocess.run", return_value=mock_result) as mock_run:
            run_sandboxed(["echo", "hi"])
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs.get("preexec_fn") is _sandbox_preexec

    def test_preserves_existing_preexec_fn(self) -> None:
        """run_sandboxed doesn't override a caller-supplied preexec_fn."""
        mock_result = subprocess.CompletedProcess(
            args=["echo"], returncode=0, stdout="", stderr=""
        )
        custom_fn = lambda: None
        with patch("moment.utils.subprocess._try_qprocess", return_value=None), \
             patch("moment.utils.subprocess.subprocess.run", return_value=mock_result) as mock_run:
            run_sandboxed(["echo", "hi"], preexec_fn=custom_fn)
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs.get("preexec_fn") is custom_fn

    def test_timeout_pass_through(self) -> None:
        """Timeout is passed through to subprocess.run."""
        mock_result = subprocess.CompletedProcess(
            args=["sleep"], returncode=0, stdout="", stderr=""
        )
        with patch("moment.utils.subprocess._try_qprocess", return_value=None), \
             patch("moment.utils.subprocess.subprocess.run", return_value=mock_result) as mock_run:
            run_sandboxed(["sleep", "1"], timeout=30)
            assert mock_run.call_args.kwargs.get("timeout") == 30


class TestPopenSandboxed:
    def test_adds_preexec_fn(self) -> None:
        """Popen_sandboxed adds _sandbox_preexec as preexec_fn."""
        with patch("moment.utils.subprocess.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            Popen_sandboxed(["echo", "hi"])
            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs.get("preexec_fn") is _sandbox_preexec
            assert call_kwargs.get("text") is True

    def test_adds_preexec_fn_with_start_new_session(self) -> None:
        """Popen_sandboxed adds preexec_fn (FD closing) even when start_new_session is set."""
        with patch("moment.utils.subprocess.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            Popen_sandboxed(["echo"], start_new_session=True)
            call_kwargs = mock_popen.call_args.kwargs
            assert call_kwargs.get("start_new_session") is True
            # preexec_fn (FD closing) should still be added
            assert call_kwargs.get("preexec_fn") is _sandbox_preexec


class TestTryQProcess:
    def test_returns_none_no_pyqt(self) -> None:
        """_try_qprocess returns None when PyQt6 is not importable."""
        import sys
        # Remove PyQt6 from sys.modules to force ImportError
        saved = {k: sys.modules.pop(k, None) for k in list(sys.modules) if "PyQt6" in k}
        try:
            result = _try_qprocess(["echo", "hi"])
            assert result is None
        finally:
            sys.modules.update({k: v for k, v in saved.items() if v is not None})

    def test_returns_none_no_qapp(self) -> None:
        """_try_qprocess returns None when no QCoreApplication exists."""
        try:
            from PyQt6 import QtCore
        except ImportError:
            pytest.skip("PyQt6 not installed")

        with patch.object(QtCore.QCoreApplication, "instance", return_value=None):
            result = _try_qprocess(["echo", "hi"])
            assert result is None
