"""Logging setup — file + (optional) systemd journal via stderr.

Provides :func:`setup_logging` which should be called once at app startup.
Log messages pass through :class:`SanitizingFilter` which redacts:

* Discord bot tokens
* Webhook URLs
* Bearer tokens in Authorization headers
* Encryption keys (hex strings 64+ chars)
* Cloud storage URLs (R2 / S3)
* Absolute home directory paths (replaced with ``~``)
* External file paths outside $HOME
* Local IP addresses

Additional features:
* :class:`JsonFormatter` — machine-parseable JSON log output
* :class:`LogDuration` — context manager / decorator for timing operations
* :func:`startup_banner` — log version, Python, platform, config at startup
* :class:`CrashDump` — save crash dumps with full diagnostic context
"""

from __future__ import annotations

import functools
import json
import logging
import os
import platform
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import moment.utils.system as system_utils

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from moment.core.config import Config

_LOG_DIR = os.path.expanduser("~/.local/share/moment")
_LOG_FILE = os.path.join(_LOG_DIR, "moment.log")
_CRASH_DIR = os.path.join(_LOG_DIR, "crash")
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3

# Home directory for path sanitization
_HOME = os.path.expanduser("~")

# ---------------------------------------------------------------------------
# Sanitization patterns (in order of application)
# ---------------------------------------------------------------------------
# Pre-compiled regex patterns — ordered to avoid overlap (most specific first)

_SANITIZE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Discord bot tokens: [A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}
    (
        re.compile(r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,38}"),
        "[DISCORD_TOKEN_REDACTED]",
    ),
    # Webhook URLs (Discord)
    (
        re.compile(r"https://discord\.com/api/webhooks/\d+/\S+"),
        "[WEBHOOK_URL_REDACTED]",
    ),
    # Bearer tokens in headers: Bearer <32+ chars>
    (
        re.compile(r"Bearer [A-Za-z0-9_\-+/=]{32,}"),
        "Bearer [TOKEN_REDACTED]",
    ),
    # R2 / S3 cloud URLs with bucket names
    (
        re.compile(r"https://[a-zA-Z0-9.\-]+\.r2\.cloudflarestorage\.com/[^\s]*"),
        "[CLOUD_URL_REDACTED]",
    ),
    (
        re.compile(r"https://s3\.[a-zA-Z0-9\-]+\.amazonaws\.com/[^\s]*"),
        "[CLOUD_URL_REDACTED]",
    ),
    # Rclone remote:path notation
    (
        re.compile(r"r2:moment/[^\s]*"),
        "[CLOUD_PATH_REDACTED]",
    ),
    # Encryption keys: hex strings of 64+ characters (standalone / in quotes)
    (
        re.compile(r"\b[A-Fa-f0-9]{64,}\b"),
        "[KEY_REDACTED]",
    ),
]

# Local IP address pattern (applied to the whole message after other redactions)
_LOCAL_IP_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:127\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)

_IN_FLIGHT_LOG_PATHS: dict[int, str] = {}  # pid → current log path (for crash dumps)


def _sanitize(msg: str) -> str:
    """Apply all sanitization patterns to a message string."""
    # 1. Replace home directory paths with ~
    msg = msg.replace(_HOME, "~")

    # 2. Apply regex patterns for tokens, URLs, keys
    for pattern, replacement in _SANITIZE_PATTERNS:
        msg = pattern.sub(replacement, msg)

    # 3. Redact local IP addresses
    msg = _LOCAL_IP_PATTERN.sub("[LOCAL_IP_REDACTED]", msg)

    return msg


class SanitizingFilter(logging.Filter):
    """Logging filter that redacts sensitive data from log records.

    Applied to all handlers so that secrets never hit disk or stderr.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize(str(record.msg))
        if record.args:
            record.args = tuple(_sanitize(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


# ===================================================================
# JSON Formatter
# ===================================================================


class JsonFormatter(logging.Formatter):
    """Logging formatter that outputs JSON objects for structured logging.

    Each log line is a single JSON object with keys:
    ``timestamp``, ``level``, ``logger``, ``message``, ``module``,
    ``function``, ``line``, ``pid``.

    If the LogRecord has a ``clip_id`` attribute, it is included as well
    so logs from different clips can be correlated.

    Usage::

        handler.setFormatter(JsonFormatter())
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "pid": record.process,
        }
        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        # Include optional correlation fields
        for attr in ("clip_id", "task_id", "request_id"):
            val = getattr(record, attr, None)
            if val is not None:
                entry[attr] = str(val)
        return json.dumps(entry, default=str)


# ===================================================================
# LogDuration — context manager / decorator
# ===================================================================


class LogDuration:
    """Context manager and decorator for timing operations.

    Logs the duration at the given level on exit (or on exception).

    As context manager::

        with LogDuration("encode clip"):
            do_encode()

    As decorator::

        @LogDuration("full pipeline")
        def run_pipeline(clip):
            ...

    The decorated function must not be a coroutine (use async helpers
    separately).

    Args:
        label: Human-readable label for the timed operation.
        level: Logging level (default ``logging.DEBUG``).
        logger_name: Logger to use (default ``"moment.performance"``).
            ``None`` falls back to the caller's logger.
        warn_threshold: If set, log a WARNING when duration exceeds
            this many seconds.
    """

    def __init__(
        self,
        label: str,
        level: int = logging.DEBUG,
        logger_name: str | None = "moment.performance",
        warn_threshold: float | None = None,
    ) -> None:
        self._label = label
        self._level = level
        self._warn_threshold = warn_threshold
        self._logger = logging.getLogger(logger_name) if logger_name else None
        self._start: float = 0.0

    def __enter__(self) -> LogDuration:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        elapsed = time.perf_counter() - self._start
        log = self._logger or logging.getLogger()

        if exc_type is not None:
            log.log(
                self._level,
                "%s failed after %.3fs with %s: %s",
                self._label,
                elapsed,
                exc_type.__name__,
                exc_val,
            )
        elif self._warn_threshold is not None and elapsed > self._warn_threshold:
            log.warning(
                "%s took %.3fs (threshold: %.1fs)",
                self._label,
                elapsed,
                self._warn_threshold,
            )
        else:
            log.log(
                self._level,
                "%s completed in %.3fs",
                self._label,
                elapsed,
            )

    def __call__(self, func: Callable) -> Callable:
        """Use as a decorator."""
        label = self._label or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with LogDuration(label, self._level, self._logger.name if self._logger else None):
                return func(*args, **kwargs)

        return wrapper


# ===================================================================
# Startup banner
# ===================================================================


def startup_banner(
    config: "Config | None" = None,
    log_path: str = "",
) -> dict[str, Any]:
    """Log diagnostic information at application startup.

    Logs version, Python version, platform, PID, config paths,
    GPU info, and FFmpeg availability.  Returns the diagnostic info
    as a dict for use elsewhere (e.g. crash dumps, diagnose CLI).

    Args:
        config: Optional Config instance for path overrides.
        log_path: Override for the log file path shown in the banner.

    Returns:
        Dict of diagnostic information.
    """
    from moment import __version__

    resolved_log = log_path or _get_current_log_path(config)

    info: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "config_dir": os.path.expanduser("~/.config/moment"),
        "data_dir": (
            config.get_path("data_dir") if config else os.path.expanduser("~/.local/share/moment")
        ),
        "log_path": resolved_log,
        "crash_dir": _CRASH_DIR,
        "nvidia_gpu": system_utils.is_nvidia_gpu(),
        "ffmpeg_path": system_utils.find_binary("ffmpeg"),
        "ffprobe_path": system_utils.find_binary("ffprobe"),
        "os": system_utils.get_os_name(),
    }

    logger = logging.getLogger("moment.startup")

    logger.info("━━━ Moment %s startup ━━━", __version__)
    logger.info(
        "Python: %s | Platform: %s | Arch: %s",
        info["python"],
        info["os"],
        info["architecture"],
    )
    logger.info("PID: %d | CWD: %s", os.getpid(), info["cwd"])
    logger.info("Config: %s  |  Data: %s", info["config_dir"], info["data_dir"])
    logger.info("Log path: %s", resolved_log)
    logger.info("GPU: %s", "NVIDIA" if info["nvidia_gpu"] else "not detected")
    logger.info(
        "FFmpeg: %s  |  FFprobe: %s",
        info["ffmpeg_path"] or "not found",
        info["ffprobe_path"] or "not found",
    )
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return info


def _get_current_log_path(config: "Config | None" = None) -> str:
    """Return the resolved log file path for the current process."""
    log_dir = config.get_path("log_dir") if config is not None else _LOG_DIR
    return os.path.join(log_dir, "moment.log")


# ===================================================================
# Crash dump handler
# ===================================================================


def _safe_qt_crash_context() -> list[str]:
    """Gather Qt-sensitive crash context without risking SIGABRT.

    Reads the recent log tail and queries ``QApplication.activeWindow()``
    defensively — any failure is captured as text rather than propagated.
    """
    lines: list[str] = []

    lines.append("Recent log lines:")
    lines.append("-" * 40)
    try:
        tail_path = _get_current_log_path()
        if os.path.isfile(tail_path):
            with open(tail_path, "rb") as fh:
                tail_text = _tail_file(fh, 40).decode("utf-8", errors="replace")
            for log_line in tail_text.splitlines():
                lines.append(f"  {log_line}")
        else:
            lines.append("  <log file not found>")
    except Exception as exc:
        lines.append(f"  <unavailable: {exc}>")
    lines.append("")

    lines.append("Qt context:")
    lines.append("-" * 40)
    try:
        from PyQt6.QtWidgets import QApplication

        qapp = QApplication.instance()
        if qapp is None:
            lines.append("  QApplication: <not running>")
        else:
            lines.append("  QApplication: running")
            active_win = None
            try:
                active_win = qapp.activeWindow()
            except Exception as exc:
                lines.append(f"  activeWindow: <error: {exc}>")
            else:
                if active_win is None:
                    lines.append("  activeWindow: <none>")
                else:
                    title = "<unknown>"
                    try:
                        title = active_win.windowTitle()
                    except Exception:
                        pass
                    lines.append(
                        f"  activeWindow: {active_win.__class__.__name__} — {title!r}"
                    )
    except Exception as exc:
        lines.append(f"  <unavailable: {exc}>")
    lines.append("")

    return lines


class CrashDump:
    """Capture and persist crash dumps with full diagnostic context.

    On an unhandled exception, saves a crash dump file to
    ``~/.local/share/moment/crash/`` with:

    * Timestamp and version info
    * Python version and platform
    * Full traceback
    * Environment info (PID, CWD)
    * System info (OS, GPU)

    Usage::

        crash = CrashDump()
        sys.excepthook = crash.excepthook
    """

    def __init__(
        self,
        log_path: str | None = None,
        crash_dir: str | Path | None = None,
    ) -> None:
        self._log_path = log_path
        self._crash_dir = Path(crash_dir) if crash_dir is not None else Path(_CRASH_DIR)

    def excepthook(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        """Exception hook — save a crash dump file.

        Does **not** log the exception (the caller / chained hook is
        responsible for that) to avoid double-logging.  Re-raises
        ``KeyboardInterrupt`` so the process can exit cleanly.
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        # Save crash dump file
        self._save_dump(exc_type, exc_value, exc_tb)

    def _save_dump(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        """Write a crash dump to disk, gathering diagnostic info."""
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%dT%H%M%SZ")
        pid = os.getpid()

        crash_dir = self._crash_dir
        crash_dir.mkdir(parents=True, exist_ok=True)

        dump_path = crash_dir / f"crash_{ts_str}_pid{pid}.txt"

        # Safely format the traceback — handle both traceback objects
        # and other formats (e.g. StackSummary).
        try:
            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        except (AttributeError, TypeError):
            tb_text = f"{exc_type.__name__}: {exc_value}\n  (traceback unavailable)"

        from moment import __version__

        # Sanitize paths in diagnostic fields (replace home with ~)
        log_path = _sanitize(self._log_path or _get_current_log_path())
        cwd = _sanitize(os.getcwd())

        lines = [
            "=" * 72,
            f"Moment Crash Report — {ts.isoformat()}",
            "=" * 72,
            "",
            f"Version:      {__version__}",
            f"Python:       {sys.version.split()[0]}",
            f"Platform:     {platform.platform()}",
            f"Architecture: {platform.machine()}",
            f"OS:           {system_utils.get_os_name()}",
            f"PID:          {pid}",
            f"CWD:          {cwd}",
            f"GPU:          {'NVIDIA' if system_utils.is_nvidia_gpu() else 'not detected'}",
            f"FFmpeg:       {system_utils.find_binary('ffmpeg') or 'not found'}",
            f"Log file:     {log_path}",
            "",
            "Traceback:",
            "-" * 40,
            tb_text.rstrip(),
            "",
        ]
        lines.extend(_safe_qt_crash_context())
        lines.extend(
            [
                "=" * 72,
                "END OF CRASH REPORT",
                "=" * 72,
                "",
            ]
        )

        try:
            dump_path.write_text("\n".join(lines), encoding="utf-8")
            # Restrict permissions
            dump_path.chmod(0o600)
            logging.getLogger("moment.crash").warning("Crash dump saved to %s", dump_path)
        except OSError as exc:
            logging.getLogger("moment.crash").error(
                "Failed to write crash dump to %s: %s", dump_path, exc
            )


# ===================================================================
# Diagnose — print system diagnostic report to stdout
# ===================================================================


def diagnose(
    config: "Config | None" = None,
    tail_lines: int = 40,
) -> dict[str, Any]:
    """Gather and return a full diagnostic report as a dict.

    This is the data source for both the ``moment diagnose`` CLI
    command and crash dump generation.

    Args:
        config: Optional Config instance for path resolution.
        tail_lines: Number of recent log lines to include (0 to skip).

    Returns:
        Dict with version, platform, paths, disk usage, and log tail.
    """
    from moment import __version__

    info: dict[str, Any] = {}
    info["moment_version"] = __version__
    info["python_version"] = sys.version
    info["platform"] = platform.platform()
    info["architecture"] = platform.machine()
    info["os_name"] = system_utils.get_os_name()
    info["pid"] = os.getpid()
    info["cwd"] = os.getcwd()
    info["nvidia_gpu"] = system_utils.is_nvidia_gpu()
    info["ffmpeg_path"] = system_utils.find_binary("ffmpeg")
    info["ffprobe_path"] = system_utils.find_binary("ffprobe")

    # Config paths
    cfg = config
    if cfg is None:
        try:
            from moment.core.config import Config

            cfg = Config()
        except Exception:
            cfg = None

    if cfg is not None:
        info["config_db"] = cfg._db_path
        info["data_dir"] = cfg.get_path("data_dir")
        info["encode_dir"] = cfg.get_path("encode_dir")
        info["recordings_dir"] = cfg.get_path("recordings_dir")
        info["log_dir"] = cfg.get_path("log_dir")
        info["replay_enabled"] = cfg.replay_enabled
        info["preferred_codec"] = cfg.get_preferred_codec()
        info["settings_count"] = len(cfg.get_all())
    else:
        info["config_db"] = "<unavailable>"
        info["data_dir"] = "<unavailable>"

    # Disk usage
    try:
        total, used, free = system_utils.disk_usage(
            cfg.get_path("data_dir") if cfg else os.path.expanduser("~")
        )
        info["disk_total_bytes"] = total
        info["disk_used_bytes"] = used
        info["disk_free_bytes"] = free
        info["disk_free_human"] = system_utils.human_size(free)
        info["disk_used_human"] = system_utils.human_size(used)
    except Exception:
        pass

    # Log file tail
    log_path = _get_current_log_path(cfg)
    info["log_path"] = log_path
    if tail_lines > 0:
        try:
            with open(log_path, "rb") as fh:
                tail_bytes = _tail_file(fh, tail_lines)
            info["log_tail"] = tail_bytes.decode("utf-8", errors="replace")
        except Exception:
            info["log_tail"] = "<unavailable>"
    else:
        info["log_tail"] = ""

    # Available storage providers
    try:
        from moment.core.uploader import list_storage_providers

        info["storage_providers"] = list_storage_providers()
    except Exception:
        info["storage_providers"] = []

    return info


def _tail_file(fh: Any, n_lines: int) -> bytes:
    """Return the last *n_lines* lines from an open binary file."""
    fh.seek(0, 2)  # EOF
    bufsize = 8192
    remaining = n_lines
    chunks: list[bytes] = []
    while remaining > 0:
        pos = fh.tell()
        if pos == 0:
            break
        read_size = min(bufsize, pos)
        fh.seek(-read_size, 1)
        chunk = fh.read(read_size)
        chunks.append(chunk)
        fh.seek(-read_size, 1)
        remaining -= chunk.count(b"\n")
    data = b"".join(reversed(chunks))
    lines = data.splitlines()
    return b"\n".join(lines[-n_lines:])


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def setup_logging(
    verbose: bool = False,
    *,
    config: "Config | None" = None,
    enable_json: bool = False,
    log_dir: Path | None = None,
) -> logging.Logger:
    """Configure the root logger and return the application logger.

    * File handler writes to ``~/.local/share/moment/moment.log``
      with rotation at 10 MB (keeps 3 backups).  Log file is set to
      ``0o600`` (owner read/write only).
    * Stream handler writes to stderr for systemd journal integration.
    * All messages pass through :class:`SanitizingFilter` which redacts
      tokens, keys, URLs, webhooks, cloud paths, and local IPs.
    * Home directory paths are replaced with ``~``.
    * Format: ``[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message``
      (or JSON if *enable_json* is ``True``).

    Args:
        verbose: If ``True``, set the log level to ``DEBUG``; otherwise ``INFO``.
        config: Optional Config for path overrides.
        enable_json: If ``True``, use :class:`JsonFormatter` instead of
            the default text format on both file and stream handlers.
        log_dir: Optional log directory override (takes precedence over
            *config*).

    Returns:
        The configured root logger.
    """
    if log_dir is not None:
        resolved_log_dir = str(log_dir)
    elif config is not None:
        resolved_log_dir = config.get_path("log_dir")
    else:
        resolved_log_dir = _LOG_DIR
    log_file = os.path.join(resolved_log_dir, "moment.log")
    Path(resolved_log_dir).mkdir(parents=True, exist_ok=True)

    # Restrict umask so RotatingFileHandler creates log files as 0o600
    old_umask = os.umask(0o077)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Remove any previously added handlers to avoid duplication on re-call
    root.handlers.clear()

    if enable_json:
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter(
            "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Sanitizing filter
    sanitize_filter = SanitizingFilter()

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(sanitize_filter)
    root.addHandler(file_handler)

    # Track path for crash dumps
    _IN_FLIGHT_LOG_PATHS[os.getpid()] = log_file

    # Restore original umask; also set permissions on existing file
    os.umask(old_umask)
    try:
        os.chmod(log_file, 0o600)
    except OSError:
        logger.debug("Failed to set permissions on log file %s", log_file)

    # Stream handler → stderr (picked up by systemd journal if applicable)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(fmt)
    stream_handler.addFilter(sanitize_filter)
    root.addHandler(stream_handler)

    return root
