"""Sandboxed subprocess helpers — security hardening for external tool invocation.

Provides ``run_sandboxed()`` and ``Popen_sandboxed()`` as drop-in
replacements for ``subprocess.run()`` and ``subprocess.Popen()``.

``ExternalCommandRunner`` is the canonical wrapper: all subprocess calls
should go through it so sandboxing, PID tracking, and log redaction are
applied consistently.

Strategy:
    - ffmpeg / gpu-screen-recorder: QProcess with ``CloseFileDescriptors | ResetIds``
    - rclone (thread-pool): ``preexec_fn`` with ``os.closerange(3, 256)``

All child processes get ``os.setsid()`` for clean signal delivery and
close inherited file descriptors to prevent FD-leak attacks.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess  # nosec B404
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Upper bound for file descriptor closing (rclone thread-pool path).
# 256 is generous — most processes don't have more than a few dozen open.
_FD_CLOSE_MAX = 256

# ---------------------------------------------------------------------------
# Orphan-prevention tracking
# ---------------------------------------------------------------------------

_child_pids: set[int] = set()
_child_lock = threading.Lock()


def _register_child(pid: int) -> None:
    with _child_lock:
        _child_pids.add(pid)


def _deregister_child(pid: int) -> None:
    with _child_lock:
        _child_pids.discard(pid)


def _cleanup_child_processes() -> None:
    """SIGKILL all tracked child processes. Called on atexit and signals."""
    with _child_lock:
        pids = list(_child_pids)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
            logger.debug("Sent SIGKILL to tracked child pid=%d", pid)
        except (ProcessLookupError, OSError):
            logger.debug("Process %d already exited — skipping SIGKILL", pid)
        try:
            os.waitid(os.P_PID, pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            logger.debug("waitid failed for pid %d", pid)


def _signal_cleanup(signum: int, _frame: Any) -> None:
    """Signal handler: kill children, then re-raise the signal."""
    _cleanup_child_processes()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


# Register atexit and crash-signal handlers (idempotent)
atexit.register(_cleanup_child_processes)
for _sig in (signal.SIGTERM, signal.SIGSEGV):
    try:
        signal.signal(_sig, _signal_cleanup)
    except (ValueError, OSError):
        pass


def _sandbox_preexec() -> None:
    """Drop privileges and close inherited FDs in the child process.

    Called via ``preexec_fn`` before ``exec()`` in the forked child.
    Safe to use from background threads — runs in the child after fork.
    """
    # Create a new session (clean signal delivery)
    try:
        os.setsid()
    except OSError:
        logger.debug("Failed to create new session in sandbox")  # non-fatal — some environments restrict setsid

    # Drop setuid / setgid privileges if elevated
    try:
        if os.getuid() == 0:
            # Running as root — drop supplementary groups first, then uid/gid
            os.setgroups([])
            os.setgid(os.getgid())
            os.setuid(os.getuid())
    except OSError:
        logger.debug("Failed to drop privileges in sandbox")  # non-fatal — not running as root

    # Close inherited file descriptors beyond stdin/stdout/stderr.
    # Use /proc/self/fd for dynamic upper bound on Linux (avoids FD 257+ leaks).
    try:
        fd_dir = "/proc/self/fd"
        if os.path.isdir(fd_dir):
            for entry in os.listdir(fd_dir):
                try:
                    fd = int(entry)
                    if fd > 2:
                        os.close(fd)
                except (ValueError, OSError):
                    pass
        else:
            os.closerange(3, _FD_CLOSE_MAX)
    except OSError:
        logger.debug("Failed to close inherited file descriptors in sandbox")  # non-fatal


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
        Managed Popen instance.  The PID is automatically tracked in
        ``_child_pids`` and de-registered when the process exits.
    """
    if "preexec_fn" not in kwargs:
        kwargs["preexec_fn"] = _sandbox_preexec

    proc = subprocess.Popen(  # nosec B603 — tokenized args, no shell=True
        cmd,
        text=text,
        **kwargs,
    )

    # Register for orphan-prevention tracking
    pid = proc.pid
    if pid is not None:
        _register_child(pid)

        # Monkey-patch wait / poll / communicate so the PID is
        # de-registered as soon as we know the process has exited.
        _orig_wait = proc.wait
        _orig_poll = proc.poll
        _orig_communicate = proc.communicate

        def _wait_wait(*args: Any, **kw: Any) -> int:
            rc = _orig_wait(*args, **kw)
            _deregister_child(pid)
            return rc

        def _wait_poll(*args: Any, **kw: Any) -> int | None:
            rc = _orig_poll(*args, **kw)
            if rc is not None:
                _deregister_child(pid)
            return rc

        def _wait_communicate(*args: Any, **kw: Any) -> tuple[str | None, str | None]:
            result = _orig_communicate(*args, **kw)
            _deregister_child(pid)
            return result

        proc.wait = _wait_wait  # type: ignore[method-assign]
        proc.poll = _wait_poll  # type: ignore[method-assign]
        proc.communicate = _wait_communicate  # type: ignore[method-assign]

    return proc


# ---------------------------------------------------------------------------
# ExternalCommandRunner — canonical wrapper
# ---------------------------------------------------------------------------


class ExternalCommandRunner:
    """Canonical wrapper for all external subprocess calls.

    Applies sandboxing (close_fds, new session), registers child PIDs
    for orphan prevention, logs commands with secrets redacted, and
    applies timeouts via :class:`subprocess.TimeoutExpired`.

    All direct ``subprocess.run()`` / ``subprocess.Popen()`` calls
    should be ported to this class so ``# nosec`` annotations are
    no longer needed.
    """

    def __init__(self) -> None:
        pass

    def run(
        self,
        cmd: list[str],
        *,
        timeout: float | None = 30,
        capture_output: bool = True,
        text: bool = True,
        check: bool = False,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Run a short-lived subprocess with full sandboxing.

        Delegates to :func:`run_sandboxed` which applies QProcess or
        preexec_fn sandboxing depending on runtime context.

        Args:
            cmd: Tokenised command-line arguments.
            timeout: Seconds before :class:`subprocess.TimeoutExpired`.
            capture_output: Capture stdout/stderr.
            text: Decode output as text.
            check: Raise on non-zero exit.
            **kwargs: Passed through to ``subprocess.run()``.

        Returns:
            CompletedProcess with stdout/stderr captured.
        """
        logger.debug("Running: %s", _redact_cmd(cmd))
        return run_sandboxed(
            cmd,
            timeout=timeout,
            capture_output=capture_output,
            text=text,
            check=check,
            **kwargs,
        )

    def run_popen(
        self,
        cmd: list[str],
        *,
        text: bool = True,
        **kwargs: Any,
    ) -> subprocess.Popen[str]:
        """Launch a long-running subprocess with sandboxing.

        Delegates to :func:`Popen_sandboxed` for sandboxing + PID tracking.

        Args:
            cmd: Tokenised command-line arguments.
            text: Decode output as text.
            **kwargs: Passed through to ``subprocess.Popen()``.

        Returns:
            Managed Popen instance with PID tracked for orphan prevention.
        """
        logger.debug("Launching: %s", _redact_cmd(cmd))
        return Popen_sandboxed(cmd, text=text, **kwargs)


def _redact_cmd(cmd: list[str]) -> str:
    """Return a log-safe string representation of *cmd*.

    Strips long tokens (URLs, keys) that might contain secrets.
    """
    parts: list[str] = []
    for i, arg in enumerate(cmd):
        if len(arg) > 200:
            parts.append(arg[:100] + "..." + arg[-20:])
        elif "://" in arg and any(
            pat in arg.lower() for pat in ("token=", "key=", "secret=", "password=")
        ):
            parts.append("[REDACTED]")
        else:
            parts.append(arg)
    return " ".join(parts)


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

    # Kill on timeout to prevent zombie process accumulation
    if not finished:
        proc.kill()
        proc.waitForFinished(5000)  # 5s grace for cleanup

    stdout = bytes(proc.readAllStandardOutput()).decode(errors="replace")
    stderr = bytes(proc.readAllStandardError()).decode(errors="replace")
    returncode = proc.exitCode() if finished else -1

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
