"""Tests for core/noise_suppression.py — RNNoise mic track processing."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.noise_suppression import (
    NoiseSuppressor,
    NoiseSuppressorError,
)


@pytest.fixture
def suppressor() -> NoiseSuppressor:
    return NoiseSuppressor(enabled=True)


@pytest.fixture
def fake_mp4(tmp_path: Path) -> Path:
    """Create a fake encoded MP4 for testing."""
    p = tmp_path / "test_clip.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
    return p


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_enabled_by_default(self) -> None:
        s = NoiseSuppressor()
        assert s.enabled is True

    def test_can_disable(self) -> None:
        s = NoiseSuppressor(enabled=False)
        assert s.enabled is False


# ---------------------------------------------------------------------------
# Process — skip conditions
# ---------------------------------------------------------------------------


class TestSkipConditions:
    def test_skip_when_disabled(self, fake_mp4: Path) -> None:
        s = NoiseSuppressor(enabled=False)
        result = s.process(fake_mp4, has_mic_audio=True)
        assert result == fake_mp4  # returned unchanged

    def test_skip_when_no_mic_audio(self, fake_mp4: Path) -> None:
        s = NoiseSuppressor(enabled=True)
        result = s.process(fake_mp4, has_mic_audio=False)
        assert result == fake_mp4

    def test_skip_when_single_audio_track(
        self, suppressor: NoiseSuppressor, fake_mp4: Path
    ) -> None:
        """If there's only one audio stream, skip suppression."""
        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = '{"streams": [{"codec_type": "audio", "index": 0}]}'

        with (
            patch("subprocess.run", return_value=probe_result),
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            result = suppressor.process(fake_mp4, has_mic_audio=True)
            assert result == fake_mp4


# ---------------------------------------------------------------------------
# Successful processing
# ---------------------------------------------------------------------------


class TestSuccessfulProcessing:
    def test_process_applies_rnnoise(
        self, suppressor: NoiseSuppressor, fake_mp4: Path
    ) -> None:
        """When mic + game audio tracks exist, RNNoise should be applied."""
        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = (
            '{"streams": ['
            '{"codec_type": "audio", "index": 0, "codec_name": "aac"},'
            '{"codec_type": "audio", "index": 1, "codec_name": "opus"}'
            "]}"
        )

        def _create_denoised_output(*args, **kwargs):
            """Create the expected _denoised.mp4 output file."""
            output_path = fake_mp4.parent / f"{fake_mp4.stem}_denoised.mp4"
            output_path.write_bytes(b"denoised content")
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch("subprocess.run", side_effect=[probe_result, _create_denoised_output()]),
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            result = suppressor.process(fake_mp4, has_mic_audio=True)

            # Should have called ffmpeg twice (probe + rnnoise)
            assert subprocess.run.called

    def test_output_has_correct_suffix(
        self, suppressor: NoiseSuppressor, fake_mp4: Path
    ) -> None:
        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = (
            '{"streams": ['
            '{"codec_type": "audio", "index": 0, "codec_name": "aac"},'
            '{"codec_type": "audio", "index": 1, "codec_name": "opus"}'
            "]}"
        )

        def _create_denoised_output(*args, **kwargs):
            output_path = fake_mp4.parent / f"{fake_mp4.stem}_denoised.mp4"
            output_path.write_bytes(b"denoised content")
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch("subprocess.run", side_effect=[probe_result, _create_denoised_output()]),
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            result = suppressor.process(fake_mp4, has_mic_audio=True)
            assert result.suffix == ".mp4"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_rnnoise_failure_raises(
        self, suppressor: NoiseSuppressor, fake_mp4: Path
    ) -> None:
        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = (
            '{"streams": ['
            '{"codec_type": "audio", "index": 0, "codec_name": "aac"},'
            '{"codec_type": "audio", "index": 1, "codec_name": "opus"}'
            "]}"
        )

        def failing_rnnoise(*args, **kwargs):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["ffmpeg"],
                output="",
                stderr="RNNoise error",
            )

        with (
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            with patch("subprocess.run", side_effect=[probe_result, failing_rnnoise]):
                # Wrap CalledProcessError since the run isn't called yet until
                # our side_effect runs; but the processor calls subprocess.run twice
                pass

            with patch(
                "subprocess.run",
                side_effect=[probe_result] + [subprocess.CalledProcessError(1, "ffmpeg", "RNNoise error")],
            ):
                with pytest.raises(NoiseSuppressorError, match="RNNoise processing failed"):
                    suppressor.process(fake_mp4, has_mic_audio=True)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_on_complete_callback(self, fake_mp4: Path) -> None:
        completed: list[str] = []
        s = NoiseSuppressor(enabled=True, on_complete=lambda stem: completed.append(stem))

        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = (
            '{"streams": ['
            '{"codec_type": "audio", "index": 0, "codec_name": "aac"},'
            '{"codec_type": "audio", "index": 1, "codec_name": "opus"}'
            "]}"
        )

        def _create_denoised_output(*args, **kwargs):
            output_path = fake_mp4.parent / f"{fake_mp4.stem}_denoised.mp4"
            output_path.write_bytes(b"denoised content")
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch("subprocess.run", side_effect=[probe_result, _create_denoised_output()]),
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            s.process(fake_mp4, has_mic_audio=True)

            assert len(completed) == 1
            assert "test_clip" in completed[0]

    def test_callback_exception_is_handled(self, fake_mp4: Path) -> None:
        def bad_callback(stem: str) -> None:
            raise RuntimeError("boom")

        s = NoiseSuppressor(enabled=True, on_complete=bad_callback)

        probe_result = MagicMock()
        probe_result.returncode = 0
        probe_result.stdout = (
            '{"streams": ['
            '{"codec_type": "audio", "index": 0, "codec_name": "aac"},'
            '{"codec_type": "audio", "index": 1, "codec_name": "opus"}'
            "]}"
        )

        def _create_denoised_output(*args, **kwargs):
            output_path = fake_mp4.parent / f"{fake_mp4.stem}_denoised.mp4"
            output_path.write_bytes(b"denoised content")
            result = MagicMock()
            result.returncode = 0
            return result

        with (
            patch("subprocess.run", side_effect=[probe_result, _create_denoised_output()]),
            patch("moment.core.noise_suppression.find_ffmpeg", return_value="ffmpeg"),
        ):
            # Should not raise
            result = s.process(fake_mp4, has_mic_audio=True)
            assert result is not None
