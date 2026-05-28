"""Encoder — ffmpeg NVENC command builder with GPU semaphore.

Constraint: Only ONE ffmpeg NVENC process may run at any time.
Enforced via :class:`threading.BoundedSemaphore`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from clip_tray.core.models import Clip, EditProfile
from clip_tray.utils.ffmpeg import FFmpegError, find_ffmpeg
from clip_tray.utils.system import ensure_dir, sanitize_stem, is_nvidia_gpu

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GPU semaphore — public so Pipeline / tests can inspect it
# ---------------------------------------------------------------------------

GPU_SEMAPHORE = threading.BoundedSemaphore(1)

# Directory for encoded output
ENCODE_DIR = os.path.expanduser("~/.local/share/clip-tray/encoded")

# Supported codecs → NVENC encoder name
_NVENC_CODECS: dict[str, str] = {
    "h264": "h264_nvenc",
    "h265": "h265_nvenc",
    "hevc": "hevc_nvenc",
    "av1": "av1_nvenc",
}

# Software fallbacks
_SOFTWARE_CODECS: dict[str, str] = {
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
    "av1": "libaom-av1",
}

# Default encode parameters per codec
_DEFAULT_CQ: dict[str, int] = {"h264": 23, "h265": 28, "hevc": 28, "av1": 30}


class EncoderError(RuntimeError):
    """Raised when encoding fails after all retry attempts."""


class Encoder:
    """Builds and executes ffmpeg NVENC encode commands.

    The class-level :data:`GPU_SEMAPHORE` ensures only one encode process
    runs at any time — a second caller blocks until the first completes.
    """

    def __init__(self, codec: str = "h264", quality: int | None = None) -> None:
        """Args:
            codec: One of ``"h264"``, ``"h265"``, ``"hevc"``, ``"av1"``.
            quality: CQ value 0–51.  Lower = better quality.  Defaults to
                a codec-appropriate value if omitted.
        """
        self._codec = codec.lower()
        self._quality = quality if quality is not None else _DEFAULT_CQ.get(self._codec, 23)
        self._quality = max(0, min(51, self._quality))
        self._nvenc_available: bool | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode(
        self,
        clip: Clip,
        profile: EditProfile | None = None,
        *,
        output_dir: str | None = None,
    ) -> Path:
        """Encode *clip* and return the path to the encoded MP4.

        Blocks until the encode completes.  Holds the GPU semaphore
        for the duration of the ffmpeg process.

        Args:
            clip: The clip to encode (must have a valid ``source_path``).
            profile: Optional edit profile with trim / audio settings.
            output_dir: Override the output directory.

        Returns:
            Path to the encoded ``.mp4`` file.

        Raises:
            EncoderError: If the encode fails.
        """
        cmd = self.build_command(clip, profile, output_dir=output_dir)
        output_path = Path(cmd[-1])

        with GPU_SEMAPHORE:
            logger.info("Encoding %s → %s …", clip.stem, output_path.name)
            find_ffmpeg()
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                msg = f"ffmpeg encode failed (code={proc.returncode}): {proc.stderr.strip()[-300:]}"
                logger.error(msg)
                raise EncoderError(msg)

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise EncoderError(f"Encoded file missing or empty: {output_path}")

        logger.info("Encode complete: %s (%s bytes)", output_path.name, output_path.stat().st_size)
        return output_path

    def build_command(
        self,
        clip: Clip,
        profile: EditProfile | None = None,
        *,
        output_dir: str | None = None,
    ) -> list[str]:
        """Build the ffmpeg command line **without** executing it.

        Useful for testing and inspection.

        Args:
            clip: Source clip.
            profile: Optional edit profile.
            output_dir: Output directory override.

        Returns:
            Tokenised command list ready for ``subprocess``.
        """
        cmd: list[str] = ["ffmpeg"]
        hwaccel = self._choose_hwaccel()
        cmd.extend(["-hwaccel", hwaccel])
        cmd.append("-y")

        # -- Trim -----------------------------------------------------------
        trim_start = None
        trim_dur = None
        if profile is not None:
            if profile.trim_start is not None:
                trim_start = profile.trim_start
                cmd.extend(["-ss", str(profile.trim_start)])
            if profile.trim_start is not None and profile.trim_end is not None:
                trim_dur = profile.trim_end - profile.trim_start
                cmd.extend(["-t", str(trim_dur)])

        # -- Input ----------------------------------------------------------
        cmd.extend(["-i", str(clip.source_path)])

        # -- Stream selection -----------------------------------------------
        # -ss before -i is already handled above for GPU-accelerated seeking.

        # -- Video encoder --------------------------------------------------
        encoder_name = self._choose_encoder()
        cmd.extend([
            "-c:v", encoder_name,
            "-preset", "p7" if "nvenc" in encoder_name else "medium",
            "-rc", "vbr" if "nvenc" in encoder_name else "crf",
            "-cq" if "nvenc" in encoder_name else "-crf", str(self._quality),
            "-b:v", "12M",
            "-maxrate", "18M",
            "-bufsize", "24M",
            "-pix_fmt", "yuv420p",
        ])

        # -- Audio ----------------------------------------------------------
        if clip.has_game_audio or clip.has_mic_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "96k"])
            # Apply volume adjustments from profile
            if profile is not None:
                filters: list[str] = []
                if clip.has_game_audio and clip.has_mic_audio:
                    filters.append(
                        f"[0:a]volume={profile.game_audio_volume}[bg];"
                        f"[1:a]volume={profile.mic_audio_volume}[mic];"
                        f"[bg][mic]amix=inputs=2:duration=first[out]"
                    )
                    cmd.extend(["-filter_complex", ";".join(filters)])
                    cmd.extend(["-map", "[out]"])
                elif clip.has_game_audio:
                    cmd.extend(["-af", f"volume={profile.game_audio_volume}"])
                elif clip.has_mic_audio:
                    cmd.extend(["-af", f"volume={profile.mic_audio_volume}"])

        # -- Output ---------------------------------------------------------
        out_dir = Path(output_dir) if output_dir else Path(ENCODE_DIR)
        ensure_dir(out_dir)
        output_path = out_dir / f"{sanitize_stem(clip.stem)}.mp4"
        cmd.append(str(output_path))

        return cmd

    # ------------------------------------------------------------------
    # Codec selection
    # ------------------------------------------------------------------

    def _choose_encoder(self) -> str:
        """Pick NVENC or software encoder based on GPU availability."""
        if is_nvidia_gpu():
            if self._codec in _NVENC_CODECS:
                return _NVENC_CODECS[self._codec]
        # Fallback
        return _SOFTWARE_CODECS.get(self._codec, "libx264")

    @staticmethod
    def _choose_hwaccel() -> str:
        """Return ``cuda`` if NVIDIA GPU is present, otherwise ``auto``."""
        return "cuda" if is_nvidia_gpu() else "auto"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def codec(self) -> str:
        """The active codec identifier."""
        return self._codec

    @property
    def quality(self) -> int:
        """The active CQ value."""
        return self._quality

    @property
    def is_nvenc_available(self) -> bool:
        """``True`` if an NVIDIA GPU with NVENC is detected."""
        if self._nvenc_available is None:
            self._nvenc_available = is_nvidia_gpu()
        return self._nvenc_available
