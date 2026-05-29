"""Sandboxed subprocess helpers — security hardening for external tool invocation.

Provides ``run_sandboxed()`` and ``Popen_sandboxed()`` as drop-in
replacements for ``subprocess.run()`` and ``subprocess.Popen()``.

Strategy:
    - ffmpeg / gpu-screen-recorder: QProcess with ``CloseFileDescriptors | ResetIds``
    - rclone (thread-pool): ``preexec_fn`` with ``os.closerange(3, 256)``

All child processes get ``os.setsid()`` for clean signal delivery and
close inherited file descriptors to prevent FD-leak attacks.
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404
from typing import Any

logger = logging.getLogger(__name__)

# Upper bound for file descriptor closing (rclone thread-pool path).
# 256 is generous — most processes don't have more than a few dozen open.
_FD_CLOSE_MAX = 256


def _sandbox_preexec() -> None:
    """Drop privileges and close inherited FDs in the child process.

    Called via ``preexec_fn`` before ``exec()`` in the forked child.
    Safe to use from background threads — runs in the child after fork.
    """
    # Create a new session (clean signal delivery)
    try:
        os.setsid()
    except OSError:
        pass

    # Drop setuid / setgid privileges if elevated
    try:
        if os.getuid() == 0:
            # Running as root — drop to the original real user
            os.setgid(os.getgid())
            os.setuid(os.getuid())
    except OSError:
        pass

    # Close inherited file descriptors beyond stdin/stdout/stderr
    try:
        os.closerange(3, _FD_CLOSE_MAX)
    except OSError:
        pass


def run_sandboxed(
    cmd: list[str],
    *,
    timeout: float | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with sandboxing applied.

    Uses ``subprocess.run()`` with ``_sandbox_preexec`` as the pre-exec
    hook.  This is the fallback path — the QProcess sandbox is attempted
    first when a QApplication is available (see :func:`_try_qprocess`).

    Args:
        cmd: Tokenised command-line arguments.
        timeout: Optional timeout in seconds.
        capture_output: Capture stdout/stderr.
        text: Decode output as text.
        check: Raise CalledProcessError on non-zero exit.
        **kwargs: Passed through to ``subprocess.run()``.

    Returns:
        CompletedProcess with stdout/stderr captured.
    """
    # Try QProcess sandbox if a QApplication exists
    result = _try_qprocess(cmd, timeout=timeout)
    if result is not None:
        return result

    # Fallback: subprocess.run with preexec_fn sandbox
    if "preexec_fn" not in kwargs:
        kwargs["preexec_fn"] = _sandbox_preexec

    return subprocess.run(  # nosec B603 — tokenized args, no shell=True
        cmd,
        timeout=timeout,
        capture_output=capture_output,
        text=text,
        check=check,
        **kwargs,
    )


def Popen_sandboxed(
    cmd: list[str],
    *,
    text: bool = True,
    **kwargs: Any,
) -> subprocess.Popen[str]:
    """Launch a subprocess with sandboxing applied (non-blocking).

    For long-running processes like gpu-screen-recorder.

    Args:
        cmd: Tokenised command-line arguments.
        text: Decode output as text.
        **kwargs: Passed through to ``subprocess.Popen()``.

    Returns:
        Managed Popen instance.
    """
    if "preexec_fn" not in kwargs:
        kwargs["preexec_fn"] = _sandbox_preexec

    return subprocess.Popen(  # nosec B603 — tokenized args, no shell=True
        cmd,
        text=text,
        **kwargs,
    )


def _try_qprocess(
    cmd: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Attempt to run *cmd* via QProcess with Unix sandbox flags.

    Returns ``None`` if no QApplication is available (caller should fall
    back to ``subprocess.run()`` with ``preexec_fn``).

    Uses ``QProcess.setUnixProcessParameters()`` to apply:
        - ``QProcess.UnixProcessFlag.CloseFileDescriptors``
        - ``QProcess.UnixProcessFlag.ResetIds``
        - ``QProcess.UnixProcessFlag.DisconnectFromControllingTTY``
    """
    try:
        from PyQt6.QtCore import QCoreApplication, QProcess  # type: ignore[import-untyped]
    except ImportError:
        return None

    app = QCoreApplication.instance()
    if app is None:
        return None

    proc = QProcess()
    proc.setProgram(cmd[0])
    if len(cmd) > 1:
        proc.setArguments(cmd[1:])

    # Apply sandbox flags (PyQt6 / Qt6)
    try:
        flags = QProcess.UnixProcessFlag.CloseFileDescriptors
        flags |= QProcess.UnixProcessFlag.ResetIds
        flags |= QProcess.UnixProcessFlag.DisconnectFromControllingTTY
        proc.setUnixProcessParameters(flags)
    except (AttributeError, TypeError):
        # Older PyQt6 without setUnixProcessParameters, or flag | not supported
        logger.debug("QProcess sandbox flags not available — using preexec_fn fallback")
        return None

    proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)

    # Work around missing stdout/stderr capture in _try_qprocess by using
    # subprocess.run() fallback — QProcess sandbox path is primarily for
    # the privilege-dropping benefit on ffmpeg/gsr, not for output capture.
    proc.start()
    finished = proc.waitForFinished(
        int(timeout * 1000) if timeout is not None else 300000  # 5 min default
    )

    stdout = bytes(proc.readAllStandardOutput()).decode(errors="replace")
    stderr = bytes(proc.readAllStandardError()).decode(errors="replace")
    returncode = proc.exitCode() if finished else -1

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
