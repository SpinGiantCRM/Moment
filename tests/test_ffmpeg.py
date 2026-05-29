"""Tests for utils/ffmpeg.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from moment.utils.ffmpeg import (
    FFmpegError,
    encode,
    find_ffmpeg,
    find_ffprobe,
    probe,
    thumbnail,
)


class TestFind:
    def test_find_ffmpeg_found(self) -> None:
        with patch("moment.utils.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert find_ffmpeg() == "ffmpeg"

    def test_find_ffmpeg_not_found(self) -> None:
        with patch("moment.utils.ffmpeg.shutil.which", return_value=None):
            # Reset cache
            import moment.utils.ffmpeg as ffmpeg_mod
            ffmpeg_mod._ffmpeg_available = None
            with pytest.raises(FFmpegError, match="ffmpeg not found"):
                find_ffmpeg()

    def test_find_ffprobe_found(self) -> None:
        with patch("moment.utils.ffmpeg.shutil.which", return_value="/usr/bin/ffprobe"):
            assert find_ffprobe() == "ffprobe"

    def test_find_ffprobe_not_found(self) -> None:
        with patch("moment.utils.ffmpeg.shutil.which", return_value=None):
            import moment.utils.ffmpeg as ffmpeg_mod
            ffmpeg_mod._ffprobe_available = None
            with pytest.raises(FFmpegError, match="ffprobe not found"):
                find_ffprobe()


class TestProbe:
    def test_success(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"format":{"filename":"test.mkv"}}', stderr=""
        )
        with (
            patch("moment.utils.ffmpeg.find_ffprobe", return_value="ffprobe"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            data = probe("test.mkv")
            assert data == {"format": {"filename": "test.mkv"}}
            mock_run.assert_called_once()

    def test_error(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Error")
        with (
            patch("moment.utils.ffmpeg.find_ffprobe", return_value="ffprobe"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(FFmpegError, match="ffprobe failed"):
                probe("test.mkv")

    def test_invalid_json(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        with (
            patch("moment.utils.ffmpeg.find_ffprobe", return_value="ffprobe"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(FFmpegError, match="invalid JSON"):
                probe("test.mkv")


class TestEncode:
    def test_returns_popen(self) -> None:
        with (
            patch("moment.utils.ffmpeg.find_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            proc = encode(["ffmpeg", "-i", "in.mkv", "out.mp4"])
            assert proc is not None
            mock_popen.assert_called_once()


class TestThumbnail:
    def test_success(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            patch("moment.utils.ffmpeg.find_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            thumbnail("in.mkv", "out.jpg", time=5.0)
            mock_run.assert_called_once()

    def test_error(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Failed")
        with (
            patch("moment.utils.ffmpeg.find_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(FFmpegError, match="thumbnail generation failed"):
                thumbnail("in.mkv", "out.jpg")
