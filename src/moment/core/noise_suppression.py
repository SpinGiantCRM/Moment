"""Noise suppression — RNNoise on mic audio track.

Applied as a post-encode step before upload.  The process:
    1. Extract mic audio track from the encoded MP4
    2. Apply RNNoise filter
    3. Remux the cleaned audio back with the original video + game audio

Requires ``ffmpeg`` compiled with ``--enable-libvmaf`` or an external
``rnnoise`` filter plugin.
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 — required for CalledProcessError exception type
from pathlib import Path
from typing import Callable

from moment.utils.ffmpeg import FFmpegError, find_ffmpeg
from moment.utils.subprocess import ExternalCommandRunner
from moment.utils.system import validate_arg

logger = logging.getLogger(__name__)

_command = ExternalCommandRunner()


class NoiseSuppressorError(RuntimeError):
    """Raised when noise suppression fails."""


class NoiseSuppressor:
    """Applies RNNoise to the mic audio track of an encoded clip.

    Usage::

        suppressor = NoiseSuppressor()
        clean_path = suppressor.process(encoded_path, has_mic_audio=True)
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        model_path: str | None = None,
        on_complete: Callable[[str], None] | None = None,
    ) -> None:
        """Args:
        enabled: Whether suppression is active.  Set to ``False`` to
            skip processing without raising.
        model_path: Path to a custom RNNoise model.  Defaults to the
            built-in ffmpeg model.
        on_complete: Called as ``callback(stem)`` when processing
            finishes.
        """
        self._enabled = enabled
        self._model_path = model_path
        self._on_complete = on_complete

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self,
        path: Path,
        *,
        has_mic_audio: bool = True,
        output_dir: str | None = None,
    ) -> Path:
        """Apply noise suppression to *path*.

        If suppression is disabled or the clip has no mic audio, the
        input is returned unchanged.

        Args:
            path: Encoded MP4 file.
            has_mic_audio: Whether the clip contains a separate mic track.
            output_dir: Directory for the processed output.  Defaults to
                the same directory as *path*.

        Returns:
            Path to the noise-suppressed file (may be the same as input
            if no processing was needed).

        Raises:
            NoiseSuppressorError: If processing fails.
        """
        if not self._enabled or not has_mic_audio:
            logger.debug(
                "Noise suppression skipped (enabled=%s, mic=%s)",
                self._enabled,
                has_mic_audio,
            )
            return path

        stem = path.stem
        out_dir = Path(output_dir) if output_dir else path.parent
        output = out_dir / f"{stem}_denoised.mp4"

        try:
            find_ffmpeg()
        except FFmpegError as exc:
            raise NoiseSuppressorError(f"ffmpeg not available: {exc}") from exc

        # 1. Probe for audio stream info
        audio_streams = self._get_audio_streams(path)
        if len(audio_streams) < 2:
            logger.info("Only one audio track; skipping suppression for %s", path.name)
            return path

        # 2. Extract mic track, apply RNNoise, remux
        try:
            self._apply_rnnoise(path, output, audio_streams)
        except subprocess.CalledProcessError as exc:
            stderr_tail = exc.stderr.strip()[-200:] if exc.stderr else ""
            raise NoiseSuppressorError(
                f"RNNoise processing failed (code={exc.returncode}): {stderr_tail}"
            ) from exc

        # Replace original
        try:
            path.unlink(missing_ok=True)
            output.rename(path)
            logger.info("Noise suppression complete: %s", path.name)
        except OSError as exc:
            raise NoiseSuppressorError(f"Cannot replace file after denoise: {exc}") from exc

        stem = path.stem
        if self._on_complete is not None:
            try:
                self._on_complete(stem)
            except Exception as exc:
                logger.exception("on_complete callback error: %s", exc)

        return path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether noise suppression is active."""
        return self._enabled

    @staticmethod
    def _get_audio_streams(path: Path) -> list[dict]:
        """Use ffprobe to find audio stream indices and codecs."""
        result = _command.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        import json

        data = json.loads(result.stdout)
        return [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]

    def _apply_rnnoise(
        self,
        input_path: Path,
        output_path: Path,
        audio_streams: list[dict],
    ) -> None:
        """Run ffmpeg with RNNoise filter on the mic track.

        Strategy:
            - Select video + game audio (stream 0:a:0) as-is
            - Extract mic audio (stream 0:a:1) → apply RNNoise → encode as AAC
            - Remux everything into a single MP4
        """
        # Build the RNNoise filter string
        if self._model_path:
            try:
                valid_path = validate_arg(
                    self._model_path,
                    pattern=r"^[a-zA-Z0-9_./-]+\.rnn$",
                )
                if not os.path.isfile(valid_path):
                    raise FileNotFoundError(f"RNNoise model not found: {valid_path}")
                arnndn_filter = f"arnndn=m={valid_path}"
            except (ValueError, FileNotFoundError) as exc:
                logger.warning("Invalid RNNoise model path, falling back to default: %s", exc)
                arnndn_filter = "arnndn"
        else:
            arnndn_filter = "arnndn"

        # Build a filter chain: take mic audio, apply RNNoise, re-encode as AAC
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            # Copy video stream
            "-c:v",
            "copy",
            # Copy game audio (first audio stream)
            "-map",
            "0:a:0",
            "-c:a:0",
            "copy",
            # Process mic audio (second audio stream) through RNNoise
            "-map",
            "0:a:1",
            "-c:a:1",
            "aac",
            "-b:a:1",
            "96k",
            "-af",
            arnndn_filter,
            str(output_path),
        ]

        logger.debug("RNNoise: %s", cmd)
        _command.run(cmd, capture_output=True, text=True, check=True, timeout=300)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise NoiseSuppressorError("RNNoise output missing or empty")
