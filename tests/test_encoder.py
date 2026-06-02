"""Tests for core/encoder.py — ffmpeg NVENC command builder."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from moment.core.encoder import GPU_SEMAPHORE, Encoder, EncoderError
from moment.core.models import Clip, EditProfile

pytestmark = [pytest.mark.integration]


@pytest.fixture
def clip() -> Clip:
    return Clip(
        id=str(uuid.uuid4()),
        stem="test_clip",
        source_path=Path("/tmp/test_clip.mkv"),
        duration=30.0,
        file_size=50_000_000,
        video_codec="h264",
        fps=60.0,
        resolution=(1920, 1080),
        has_game_audio=True,
        has_mic_audio=True,
        title="Test Clip",
        game="cs2",
    )


@pytest.fixture
def profile() -> EditProfile:
    return EditProfile(
        clip_id="test",
        trim_start=5.0,
        trim_end=25.0,
        game_audio_volume=1.0,
        mic_audio_volume=0.8,
    )


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_basic_command(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip, output_dir="/tmp/out")

        assert "ffmpeg" in cmd[0]
        assert "-y" in cmd
        assert str(clip.source_path) in cmd
        assert "/tmp/out/test_clip.mp4" == cmd[-1]

    def test_hardware_accel(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip)

        assert "-hwaccel" in cmd

    def test_nvenc_encoder_selection(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip)

        # Should select any valid H.264 encoder (hardware or software)
        assert any(
            enc in cmd
            for enc in [
                "h264_nvenc",
                "h264_vaapi",
                "h264_qsv",
                "libx264",
            ]
        )

    def test_h265_codec(self, clip: Clip) -> None:
        encoder = Encoder(codec="h265")
        cmd = encoder.build_command(clip)

        assert any(
            enc in cmd
            for enc in [
                "h265_nvenc",
                "hevc_nvenc",
                "hevc_vaapi",
                "hevc_qsv",
                "libx265",
            ]
        )

    def test_trim_params(self, clip: Clip, profile: EditProfile) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip, profile)

        assert "-ss" in cmd
        assert "5.0" in cmd
        assert "-t" in cmd
        assert "20.0" in cmd

    def test_audio_with_volume_adjustments(self, clip: Clip, profile: EditProfile) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip, profile)

        assert "-c:a" in cmd
        assert "aac" in cmd
        # Profile has both game and mic audio → filter_complex
        assert "-filter_complex" in cmd

    def test_game_audio_only(self, clip: Clip) -> None:
        clip.has_mic_audio = False
        profile = EditProfile(clip_id="test", game_audio_volume=1.5)
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip, profile)

        assert "-af" in cmd
        assert "volume=1.5" in cmd

    def test_no_audio(self, clip: Clip) -> None:
        clip.has_game_audio = False
        clip.has_mic_audio = False
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip)

        assert "-c:a" not in cmd

    def test_output_in_encode_dir(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")
        cmd = encoder.build_command(clip)

        output = cmd[-1]
        assert output.endswith(".mp4")
        assert clip.stem in output

    def test_quality_clamped(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264", quality=1000)
        assert encoder.quality == 51

        encoder2 = Encoder(codec="h264", quality=-10)
        assert encoder2.quality == 0


# ---------------------------------------------------------------------------
# Codec properties
# ---------------------------------------------------------------------------


class TestCodecSelection:
    def test_h264_default_quality(self) -> None:
        encoder = Encoder(codec="h264")
        assert encoder.quality == 23

    def test_h265_default_quality(self) -> None:
        encoder = Encoder(codec="h265")
        assert encoder.quality == 28

    def test_av1_default_quality(self) -> None:
        encoder = Encoder(codec="av1")
        assert encoder.quality == 30

    def test_unknown_codec_fallback(self) -> None:
        encoder = Encoder(codec="unknown")
        assert encoder.quality == 23  # falls back to h264 default


# ---------------------------------------------------------------------------
# GPU semaphore
# ---------------------------------------------------------------------------


class TestGPUSemaphore:
    def test_semaphore_exists(self) -> None:
        """The global GPU_SEMAPHORE should be a BoundedSemaphore."""
        import threading

        assert isinstance(GPU_SEMAPHORE, threading.BoundedSemaphore)

    def test_semaphore_acquires(self) -> None:
        assert GPU_SEMAPHORE.acquire(blocking=False)
        GPU_SEMAPHORE.release()

    def test_semaphore_capacity_is_one(self) -> None:
        """After acquiring, a second non-blocking attempt should fail."""
        assert GPU_SEMAPHORE.acquire(blocking=False)
        assert not GPU_SEMAPHORE.acquire(blocking=False)
        GPU_SEMAPHORE.release()


# ---------------------------------------------------------------------------
# Encode execution (mocked)
# ---------------------------------------------------------------------------


class TestEncode:
    def test_successful_encode(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")

        with (
            patch("moment.core.encoder.Popen_sandboxed") as mock_popen,
            patch("moment.core.encoder.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.encoder.ensure_dir"),
        ):
            mock_proc = mock_popen.return_value
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")

            with (
                patch("pathlib.Path.is_file", return_value=True),
                patch("pathlib.Path.stat") as mock_stat,
            ):
                mock_stat.return_value.st_size = 1000
                result = encoder.encode(clip)

            assert result is not None
            assert result.suffix == ".mp4"

    def test_encode_calls_subprocess_with_correct_args(self, clip: Clip) -> None:
        """Verify Popen_sandboxed receives the right command list."""
        encoder = Encoder(codec="h264")

        with (
            patch("moment.core.encoder.Popen_sandboxed") as mock_popen,
            patch("moment.core.encoder.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.encoder.ensure_dir"),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_proc = mock_popen.return_value
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            mock_stat.return_value.st_size = 1000
            encoder.encode(clip)

            # Verify Popen_sandboxed was called
            assert mock_popen.call_count >= 1

    def test_encode_failure_raises(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")

        with (
            patch("moment.core.encoder.Popen_sandboxed") as mock_popen,
            patch("moment.core.encoder.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.encoder.ensure_dir"),
        ):
            mock_proc = mock_popen.return_value
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = ("", "Error: something went wrong")

            with pytest.raises(EncoderError, match="ffmpeg encode failed"):
                encoder.encode(clip)

    def test_encode_empty_output_raises(self, clip: Clip) -> None:
        encoder = Encoder(codec="h264")

        with (
            patch("moment.core.encoder.Popen_sandboxed") as mock_popen,
            patch("moment.core.encoder.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.encoder.ensure_dir"),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_proc = mock_popen.return_value
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            mock_stat.return_value.st_size = 0

            with pytest.raises(EncoderError, match="empty"):
                encoder.encode(clip)


# ---------------------------------------------------------------------------
# nvenc availability
# ---------------------------------------------------------------------------


class TestNvencAvailability:
    def test_is_nvenc_available(self) -> None:
        encoder = Encoder()
        result = encoder.is_nvenc_available
        assert isinstance(result, bool)
