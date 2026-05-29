"""Tests for utils/system.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from moment.utils.system import (
    disk_usage,
    ensure_dir,
    find_binary,
    get_local_ip,
    get_os_name,
    human_size,
    is_nvidia_gpu,
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
        import subprocess
        with (
            patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
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
