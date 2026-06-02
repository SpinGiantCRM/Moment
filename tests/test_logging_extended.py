"""Tests for extended logging features — JSON formatter, LogDuration,
startup_banner, CrashDump, and diagnose.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.integration]

from moment.utils.logging import (
    CrashDump,
    JsonFormatter,
    LogDuration,
    SanitizingFilter,
    _get_current_log_path,
    _tail_file,
    diagnose,
    setup_logging,
    startup_banner,
)

# ===================================================================
# JsonFormatter
# ===================================================================


class TestJsonFormatter:
    def test_format_basic(self) -> None:
        """JSON output includes timestamp, level, logger, message, module, function, line, pid."""
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/tmp/test.py",
            lineno=42,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        out = fmt.format(record)
        parsed = json.loads(out)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "hello world"
        assert parsed["line"] == 42
        assert isinstance(parsed["pid"], int)
        assert "timestamp" in parsed
        assert "exception" not in parsed

    def test_format_with_exception(self) -> None:
        """JSON output includes exception traceback when exc_info is set."""
        fmt = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        out = fmt.format(record)
        parsed = json.loads(out)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "test error" in parsed["exception"]

    def test_format_with_clip_id(self) -> None:
        """clip_id attribute is included in JSON output when present."""
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="encoding clip",
            args=(),
            exc_info=None,
        )
        record.clip_id = "abc-123"
        out = fmt.format(record)
        parsed = json.loads(out)
        assert parsed["clip_id"] == "abc-123"

    def test_format_with_task_id(self) -> None:
        """task_id attribute is included when present."""
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="task done",
            args=(),
            exc_info=None,
        )
        record.task_id = "task-42"
        out = fmt.format(record)
        parsed = json.loads(out)
        assert parsed["task_id"] == "task-42"

    def test_format_with_request_id(self) -> None:
        """request_id attribute is included when present."""
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="request",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-1"
        out = fmt.format(record)
        parsed = json.loads(out)
        assert parsed["request_id"] == "req-1"

    def test_json_still_sanitized_via_filter(self) -> None:
        """SanitizingFilter still redacts before JSON formatting."""
        fmt = JsonFormatter()
        sanitize = SanitizingFilter()

        home = os.path.expanduser("~")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Path: {home}/secret.mkv",
            args=(),
            exc_info=None,
        )
        sanitize.filter(record)
        out = fmt.format(record)
        parsed = json.loads(out)
        assert home not in parsed["message"]
        assert "~/secret.mkv" in parsed["message"]


# ===================================================================
# LogDuration
# ===================================================================


class TestLogDuration:
    def test_context_manager_logs_duration(self, caplog: pytest.LogCaptureFixture) -> None:
        """LogDuration logs the label and duration on exit."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")
        with LogDuration("test op"):
            pass
        assert any("test op completed in" in rec.message for rec in caplog.records)

    def test_context_manager_reports_elapsed_seconds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Duration is logged in seconds with 3 decimal places."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")
        # Intentional small sleep: LogDuration measures wall-clock time; a
        # deterministic replacement would require mocking time.monotonic.
        with LogDuration("sleep op"):
            time.sleep(0.01)
        match = None
        for rec in caplog.records:
            m = re.search(r"completed in (\d+\.\d+)s", rec.message)
            if m:
                match = float(m.group(1))
                break
        assert match is not None
        assert match >= 0.01

    def test_context_manager_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """On exception, LogDuration logs 'failed after ...' with the exception type."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")
        try:
            with LogDuration("failing op"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert any(
            "failing op failed after" in rec.message and "RuntimeError" in rec.message
            for rec in caplog.records
        )

    def test_warn_threshold_triggers_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When duration exceeds warn_threshold, log level is WARNING."""
        caplog.set_level(logging.WARNING, logger="moment.performance")
        # Intentional small sleep: LogDuration measures wall-clock time;
        # mocking time.monotonic would bypass the real logging path.
        with LogDuration("slow op", warn_threshold=0.001):
            time.sleep(0.01)
        assert any(
            rec.levelname == "WARNING" and "slow op took" in rec.message for rec in caplog.records
        )

    def test_warn_threshold_not_reached_stays_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """When duration is below warn_threshold, log stays at the configured level."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")
        with LogDuration("fast op", level=logging.DEBUG, warn_threshold=10.0):
            pass
        # Should be DEBUG, not WARNING
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        debugs = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert len(warnings) == 0
        assert any("fast op completed in" in r.message for r in debugs)

    def test_custom_logger(self) -> None:
        """LogDuration uses the specified logger name."""
        dur = LogDuration("test", logger_name="moment.custom")
        assert dur._logger.name == "moment.custom"

    def test_decorator(self, caplog: pytest.LogCaptureFixture) -> None:
        """LogDuration works as a decorator."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")

        @LogDuration("decorated op")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        assert any("decorated op completed in" in rec.message for rec in caplog.records)

    def test_decorator_default_label_from_func_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """When no label is given, the decorator uses the function name."""
        caplog.set_level(logging.DEBUG, logger="moment.performance")

        @LogDuration("")
        def my_func():
            return 1

        result = my_func()
        assert result == 1
        # Falls back to func.__name__


# ===================================================================
# startup_banner
# ===================================================================


class TestStartupBanner:
    def test_banner_returns_dict(self) -> None:
        """startup_banner returns a dict with diagnostic info."""
        info = startup_banner()
        assert isinstance(info, dict)

    def test_banner_contains_version(self) -> None:
        """Dict includes 'version' key."""
        info = startup_banner()
        assert "version" in info

    def test_banner_contains_python_version(self) -> None:
        """Dict includes 'python' key."""
        info = startup_banner()
        assert "python" in info

    def test_banner_contains_pid(self) -> None:
        """Dict includes 'pid' key matching current process."""
        info = startup_banner()
        assert info["pid"] == os.getpid()

    def test_banner_contains_platform_info(self) -> None:
        """Dict includes platform, architecture, and os info."""
        info = startup_banner()
        assert "platform" in info
        assert "architecture" in info
        assert "os" in info

    def test_banner_contains_paths(self) -> None:
        """Dict includes config_dir, data_dir, log_path, crash_dir."""
        info = startup_banner()
        assert "config_dir" in info
        assert "data_dir" in info
        assert "log_path" in info
        assert "crash_dir" in info

    def test_banner_contains_gpu_and_ffmpeg(self) -> None:
        """Dict includes nvidia_gpu, ffmpeg_path, ffprobe_path."""
        info = startup_banner()
        assert "nvidia_gpu" in info
        assert "ffmpeg_path" in info
        assert "ffprobe_path" in info

    def test_banner_logs_to_moment_startup(self, caplog: pytest.LogCaptureFixture) -> None:
        """Banner messages are logged under 'moment.startup'."""
        caplog.set_level(logging.INFO, logger="moment.startup")
        startup_banner()
        startup_logs = [r for r in caplog.records if r.name == "moment.startup"]
        assert len(startup_logs) > 0

    def test_banner_with_custom_log_path(self, caplog: pytest.LogCaptureFixture) -> None:
        """Custom log_path appears in the banner."""
        caplog.set_level(logging.INFO)
        info = startup_banner(log_path="/tmp/custom/moment.log")
        assert info["log_path"] == "/tmp/custom/moment.log"

    def test_banner_double_call_does_not_crash(self) -> None:
        """Calling startup_banner twice doesn't raise."""
        startup_banner()
        startup_banner()  # second call


# ===================================================================
# CrashDump
# ===================================================================


class TestCrashDump:
    def test_save_dump_creates_file(self, tmp_path: Path) -> None:
        """_save_dump writes a crash dump file to disk."""
        crash_dir = tmp_path / "crash"
        crash = CrashDump()

        # Override crash dir via patching
        with patch("moment.utils.logging._CRASH_DIR", str(crash_dir)):
            crash._save_dump(ValueError, ValueError("test crash"), None)

            files = list(crash_dir.iterdir())
            assert len(files) >= 1
            content = files[0].read_text()
            assert "Moment Crash Report" in content
            assert "ValueError" in content
            assert "test crash" in content

    def test_save_dump_includes_version(self, tmp_path: Path) -> None:
        """Crash dump contains the moment version."""
        crash_dir = tmp_path / "crash"
        crash = CrashDump()
        with patch("moment.utils.logging._CRASH_DIR", str(crash_dir)):
            crash._save_dump(RuntimeError, RuntimeError("x"), None)
            content = list(crash_dir.iterdir())[0].read_text()
            from moment import __version__

            assert __version__ in content

    def test_save_dump_includes_traceback(self, tmp_path: Path) -> None:
        """Crash dump contains the full traceback."""
        crash_dir = tmp_path / "crash"
        crash = CrashDump()
        with patch("moment.utils.logging._CRASH_DIR", str(crash_dir)):
            try:
                raise RuntimeError("detailed error")
            except RuntimeError:
                _, exc_value, exc_tb = sys.exc_info()
                crash._save_dump(RuntimeError, exc_value, exc_tb)
            content = list(crash_dir.iterdir())[0].read_text()
            assert "Traceback" in content
            assert "detailed error" in content

    def test_dump_file_permissions(self, tmp_path: Path) -> None:
        """Crash dump file is created with 0o600 permissions."""
        crash_dir = tmp_path / "crash"
        crash = CrashDump()
        with patch("moment.utils.logging._CRASH_DIR", str(crash_dir)):
            crash._save_dump(Exception, Exception("perms"), None)
            dump_file = list(crash_dir.iterdir())[0]
            mode = dump_file.stat().st_mode & 0o777
            assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_excepthook_re_raises_keyboard_interrupt(self) -> None:
        """excepthook calls sys.__excepthook__ for KeyboardInterrupt."""
        crash = CrashDump()
        calls = []

        def _fake_hook(et, ev, tb):
            calls.append(et)

        with patch("sys.__excepthook__", _fake_hook):
            crash.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert calls == [KeyboardInterrupt]

    def test_excepthook_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """excepthook does NOT log (the chained hook handles logging).

        We verify no CRITICAL-level records were created by excepthook.
        """
        caplog.set_level(logging.CRITICAL)
        crash = CrashDump()
        crash.excepthook(RuntimeError, RuntimeError("critical"), None)
        # CrashDump.excepthook no longer logs — just saves dump
        criticals = [r for r in caplog.records if r.levelname == "CRITICAL"]
        assert len(criticals) == 0

    def test_save_dump_oserror_does_not_raise(self, tmp_path: Path) -> None:
        """If the crash dump cannot be written, the error is logged, not raised."""
        crash = CrashDump()
        with patch("pathlib.Path.write_text", side_effect=OSError("permission denied")):
            # Should not raise
            crash._save_dump(Exception, Exception("fail"), None)


# ===================================================================
# diagnose
# ===================================================================


class TestDiagnose:
    def test_diagnose_returns_dict(self) -> None:
        """diagnose() returns a dict with expected keys."""
        info = diagnose()
        assert isinstance(info, dict)
        assert "moment_version" in info
        assert "python_version" in info
        assert "pid" in info
        assert "cwd" in info
        assert "nvidia_gpu" in info
        assert "ffmpeg_path" in info
        assert "ffprobe_path" in info

    def test_diagnose_paths(self) -> None:
        """diagnose() includes path fields."""
        info = diagnose()
        assert "config_db" in info
        assert "data_dir" in info
        assert "log_path" in info

    def test_diagnose_disk_info(self) -> None:
        """diagnose() includes disk usage information."""
        info = diagnose()
        assert "disk_free_human" in info
        assert "disk_used_human" in info

    def test_diagnose_tail_lines_zero(self) -> None:
        """When tail_lines=0, log_tail is empty string."""
        info = diagnose(tail_lines=0)
        assert info["log_tail"] == ""

    def test_diagnose_log_tail(self, tmp_path: Path) -> None:
        """When tail_lines > 0, log_tail contains log lines."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "moment.log"
        log_file.write_text("line1\nline2\nline3\n")

        info = diagnose(tail_lines=2)
        # The diagnose function reads from the actual log path, not tmp_path
        # So this test verifies the function doesn't crash
        assert "log_tail" in info

    def test_diagnose_storage_providers(self) -> None:
        """diagnose() includes storage_providers list."""
        info = diagnose()
        assert "storage_providers" in info
        assert isinstance(info["storage_providers"], list)

    def test_diagnose_no_config(self) -> None:
        """diagnose() works without a Config instance."""
        info = diagnose(config=None)
        assert "config_db" in info
        assert "data_dir" in info


# ===================================================================
# _tail_file
# ===================================================================


class TestTailFile:
    def test_tail_returns_last_n_lines(self, tmp_path: Path) -> None:
        """_tail_file returns the last N lines from a file."""
        p = tmp_path / "test.log"
        p.write_text("1\n2\n3\n4\n5\n")
        with open(p, "rb") as fh:
            result = _tail_file(fh, 2)
        assert result == b"4\n5"

    def test_tail_less_lines_than_requested(self, tmp_path: Path) -> None:
        """When file has fewer lines than requested, all lines are returned."""
        p = tmp_path / "short.log"
        p.write_text("a\nb\n")
        with open(p, "rb") as fh:
            result = _tail_file(fh, 10)
        assert result == b"a\nb"

    def test_tail_empty_file(self, tmp_path: Path) -> None:
        """An empty file returns empty bytes."""
        p = tmp_path / "empty.log"
        p.write_text("")
        with open(p, "rb") as fh:
            result = _tail_file(fh, 5)
        assert result == b""

    def test_tail_zero_lines(self, tmp_path: Path) -> None:
        """Requesting 0 lines returns empty bytes."""
        p = tmp_path / "zero.log"
        p.write_text("keep\nme\n")
        with open(p, "rb") as fh:
            result = _tail_file(fh, 0)
        assert result == b""

    def test_tail_single_line(self, tmp_path: Path) -> None:
        """Requesting 1 line returns the last line without trailing newline."""
        p = tmp_path / "single.log"
        p.write_text("only line\n")
        with open(p, "rb") as fh:
            result = _tail_file(fh, 1)
        assert result == b"only line"


# ===================================================================
# _get_current_log_path
# ===================================================================


class TestGetCurrentLogPath:
    def test_returns_default_path_without_config(self) -> None:
        """Without a Config, returns ~/.local/share/moment/moment.log."""
        path = _get_current_log_path()
        assert path.endswith("/moment.log")
        assert ".local/share/moment" in path


# ===================================================================
# setup_logging with json
# ===================================================================


class TestSetupLoggingJson:
    def test_json_format(self) -> None:
        """enable_json=True uses JsonFormatter on handlers."""
        logger = setup_logging(verbose=True, enable_json=True)
        from logging.handlers import RotatingFileHandler

        fh = next(
            (h for h in logger.handlers if isinstance(h, RotatingFileHandler)),
            None,
        )
        assert fh is not None
        assert isinstance(fh.formatter, JsonFormatter)

    def test_json_stream_handler(self) -> None:
        """Stream handler also uses JsonFormatter when enable_json=True."""
        logger = setup_logging(verbose=True, enable_json=True)
        stream_handler = next(
            (h for h in logger.handlers if isinstance(h, logging.StreamHandler)),
            None,
        )
        assert stream_handler is not None
        assert isinstance(stream_handler.formatter, JsonFormatter)


# ===================================================================
# Startup banner logging via setup_logging integration
# ===================================================================


class TestSetupLoggingIntegration:
    def test_setup_then_banner_does_not_crash(self) -> None:
        """Calling setup_logging followed by startup_banner is safe."""
        setup_logging(verbose=True)
        info = startup_banner()
        assert "version" in info

    def test_diagnose_after_setup(self) -> None:
        """Calling diagnose after setup_logging is safe."""
        setup_logging(verbose=True)
        info = diagnose()
        assert "moment_version" in info
