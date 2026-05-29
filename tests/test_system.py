"""Tests for utils/system.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.utils.system import (
    disk_usage,
    ensure_dir,
    find_binary,
    get_local_ip,
    get_os_name,
    human_size,
    is_nvidia_gpu,
    validate_arg,
)


class TestHumanSize:
    def test_bytes(self) -> None:
        assert human_size(0) == "0 B"
        assert human_size(500) == "500 B"
        assert human_size(1023) == "1023 B"

    def test_kilobytes(self) -> None:
        assert human_size(1024) == "1.0 KB"
        assert human_size(2048) == "2.0 KB"

    def test_megabytes(self) -> None:
        assert human_size(1024 * 1024) == "1.0 MB"
        assert human_size(50 * 1024 * 1024) == "50.0 MB"

    def test_gigabytes(self) -> None:
        assert human_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_terabytes(self) -> None:
        assert human_size(3 * 1024 * 1024 * 1024 * 1024) == "3.0 TB"

    def test_negative(self) -> None:
        assert human_size(-1) == "-1 B"


class TestDiskUsage:
    def test_returns_tuple_of_ints(self) -> None:
        total, used, free = disk_usage("/")
        assert isinstance(total, int)
        assert isinstance(used, int)
        assert isinstance(free, int)
        assert total > 0
        assert used >= 0
        assert free >= 0


class TestEnsureDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dir(Path(tmp) / "a" / "b" / "c")
            assert p.is_dir()
            assert p.exists()

    def test_returns_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = ensure_dir(tmp)
            assert p == Path(tmp).resolve()


class TestFindBinary:
    def test_found(self) -> None:
        assert find_binary("ls") is not None

    def test_not_found(self) -> None:
        assert find_binary("nonexistent_binary_xyz_123") is None


class TestNvidiaGPU:
    def test_returns_bool(self) -> None:
        result = is_nvidia_gpu()
        assert isinstance(result, bool)

    def test_nvidia_smi_found(self) -> None:
        import subprocess as sp_mod
        with (
            patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = sp_mod.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            # Reset cache
            import moment.utils.system as sys_mod
            sys_mod._nvidia_check = None
            assert is_nvidia_gpu() is True

    def test_nvidia_smi_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            import moment.utils.system as sys_mod
            sys_mod._nvidia_check = None
            assert is_nvidia_gpu() is False


class TestGetLocalIP:
    def test_returns_string_or_none(self) -> None:
        ip = get_local_ip()
        assert ip is None or isinstance(ip, str)


class TestGetOSName:
    def test_returns_string(self) -> None:
        name = get_os_name()
        assert isinstance(name, str)
        assert len(name) > 0


# ---------------------------------------------------------------------------
# validate_arg
# ---------------------------------------------------------------------------


class TestValidateArg:
    def test_empty_string_passes_through(self) -> None:
        """Empty strings are returned as-is (callers treat as 'no override')."""
        assert validate_arg("") == ""

    def test_valid_device_names(self) -> None:
        """Common audio device names should pass validation."""
        assert validate_arg("default_output") == "default_output"
        assert validate_arg("alsa_output.pci-0000_00_1f.3.analog-stereo") == (
            "alsa_output.pci-0000_00_1f.3.analog-stereo"
        )
        assert validate_arg("Built-in Audio Analog Stereo") == (
            "Built-in Audio Analog Stereo"
        )
        assert validate_arg("output") == "output"
        assert validate_arg("input") == "input"

    def test_alphanumeric_and_hyphen(self) -> None:
        assert validate_arg("my-device_1") == "my-device_1"
        assert validate_arg("USB-Audio, Device/2") == "USB-Audio, Device/2"

    def test_rejects_shell_injection(self) -> None:
        """Classic shell injection strings should raise ValueError."""
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("-o;/tmp/evil")

    def test_rejects_command_injection(self) -> None:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("'; rm -rf /")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("';../etc/passwd")

    def test_rejects_backticks(self) -> None:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("`id`")

    def test_rejects_dollar_sign(self) -> None:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("$(whoami)")

    def test_custom_pattern_rnn(self) -> None:
        """RNNoise model path pattern should validate .rnn files."""
        rnn_pattern = r"^[a-zA-Z0-9_./-]+\.rnn$"
        assert validate_arg("models/voice.rnn", pattern=rnn_pattern) == "models/voice.rnn"
        assert validate_arg("/usr/share/rnnoise/model.rnn", pattern=rnn_pattern) == (
            "/usr/share/rnnoise/model.rnn"
        )

    def test_custom_pattern_rnn_rejects_non_rnn(self) -> None:
        """Non-.rnn paths should be rejected by the rnn pattern."""
        rnn_pattern = r"^[a-zA-Z0-9_./-]+\.rnn$"
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("model.so", pattern=rnn_pattern)
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("'; rm -rf /", pattern=rnn_pattern)

    def test_custom_pattern_rejects_spaces(self) -> None:
        """A pattern without spaces should reject values containing spaces."""
        strict = r"^[a-zA-Z0-9_./-]+$"
        assert validate_arg("ok", pattern=strict) == "ok"
        with pytest.raises(ValueError, match="must match pattern"):
            validate_arg("not ok", pattern=strict)
