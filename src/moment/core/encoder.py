"""Encoder — ffmpeg hardware-accelerated command builder with GPU semaphore.

Supports NVIDIA NVENC, AMD VAAPI, Intel QSV, and software (libx264).
Constraint: Only ONE ffmpeg GPU encode process may run at any time.
Enforced via :class:`threading.BoundedSemaphore`.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from moment.core.models import Clip, EditProfile
from moment.utils.ffmpeg import (
    _VENDOR_ENCODERS,
    _encoder_works,
    detect_best_encoder,
    find_ffmpeg,
)
from moment.utils.subprocess import Popen_sandboxed
from moment.utils.system import ensure_dir, is_nvidia_gpu, sanitize_stem

if TYPE_CHECKING:
    from moment.core.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GPU semaphore — public so Pipeline / tests can inspect it; kept as
# a module-level default for backward compat.  Each Encoder instance
# now creates its own semaphore sized from ``Config.get("encode_concurrency")``.
# ---------------------------------------------------------------------------

GPU_SEMAPHORE = threading.BoundedSemaphore(1)

# Directory for encoded output (default; override via Config.get_path("encode_dir"))
_DEFAULT_ENCODE_DIR = os.path.expanduser("~/.local/share/moment/encoded")


# ---------------------------------------------------------------------------
# Multi-vendor codec matrix — imported from ffmpeg.py to avoid duplication

# Full list of all known encoders (flat)
_ALL_ENCODERS: list[str] = [
    enc for vendor in ("nvidia", "amd", "intel") for enc in _VENDOR_ENCODERS[vendor].values()
]

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

    The class-level :data:`GPU_SEMAPHORE` is kept for backward-compat;
    each instance creates its own semaphore sized from config.
    """

    def __init__(
        self, codec: str = "h264", quality: int | None = None, config: "Config | None" = None
    ) -> None:
        """Args:
        codec: One of ``"h264"``, ``"h265"``, ``"hevc"``, ``"av1"``.
        quality: CQ value 0–51.  Lower = better quality.  Defaults to
            a codec-appropriate value if omitted.
        config: Optional Config for path overrides and encode concurrency.
        """
        self._codec = codec.lower()
        self._quality = quality if quality is not None else _DEFAULT_CQ.get(self._codec, 23)
        self._quality = max(0, min(51, self._quality))
        self._nvenc_available: bool | None = None
        self._config = config

        # Per-instance GPU semaphore sized from config
        concurrency = 1
        if config is not None:
            concurrency = max(1, min(8, config.get("encode_concurrency", 1)))
        self._gpu_semaphore = threading.BoundedSemaphore(concurrency)
        if concurrency > 1:
            logger.info("GPU encode concurrency set to %d", concurrency)

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

        with self._gpu_semaphore:
            logger.info("Encoding %s → %s …", clip.stem, output_path.name)
            find_ffmpeg()
            proc = Popen_sandboxed(cmd)
            try:
                stdout, stderr = proc.communicate()
            except Exception:
                proc.kill()
                raise
            if proc.returncode != 0:
                msg = f"ffmpeg encode failed (code={proc.returncode}): {stderr.strip()[-300:]}"
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
        encoder_name = self._choose_encoder()
        hwaccel = self._choose_hwaccel(encoder_name)
        cmd.extend(["-hwaccel", hwaccel])
        cmd.append("-y")

        # -- Trim -----------------------------------------------------------
        trim_dur = None
        if profile is not None:
            if profile.trim_start is not None:
                cmd.extend(["-ss", str(profile.trim_start)])
            if profile.trim_start is not None and profile.trim_end is not None:
                trim_dur = profile.trim_end - profile.trim_start
                cmd.extend(["-t", str(trim_dur)])

        # -- Input ----------------------------------------------------------
        cmd.extend(["-i", str(clip.source_path)])

        # -- Stream selection -----------------------------------------------
        # -ss before -i is already handled above for GPU-accelerated seeking.

        # -- Video encoder --------------------------------------------------
        cmd.extend(
            [
                "-c:v",
                encoder_name,
                "-preset",
                "p7" if "nvenc" in encoder_name else "medium",
                "-rc",
                "vbr" if "nvenc" in encoder_name else "crf",
                "-cq" if "nvenc" in encoder_name else "-crf",
                str(self._quality),
                "-b:v",
                "12M",
                "-maxrate",
                "18M",
                "-bufsize",
                "24M",
                "-pix_fmt",
                "yuv420p",
            ]
        )

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
        out_dir = (
            Path(output_dir)
            if output_dir
            else Path(self._config.get_path("encode_dir") if self._config else _DEFAULT_ENCODE_DIR)
        )
        ensure_dir(out_dir)
        output_path = out_dir / f"{sanitize_stem(clip.stem)}.mp4"
        cmd.append(str(output_path))

        return cmd

    # ------------------------------------------------------------------
    # Codec selection (GPU-agnostic)
    # ------------------------------------------------------------------

    def _choose_encoder(self) -> str:
        """Select the best hardware or software encoder for the current codec.

        Priority:
            1. If Config has a ``preferred_codec`` set (not "auto"), use it directly.
            2. Otherwise use :func:`~moment.utils.ffmpeg.detect_best_encoder`
               to auto-detect the best available encoder.
            3. If the detected encoder doesn't match the codec family, fall
               back to the software encoder for that codec.
        """
        cfg = self._config

        # Explicit override from Config
        if cfg is not None:
            preferred = cfg.get_preferred_codec()
            if preferred and preferred != "auto":
                # Validate that the user's choice actually works
                if _encoder_works(preferred):
                    logger.info("Using preferred codec from config: %s", preferred)
                    return preferred
                logger.warning(
                    "Preferred codec %s not available, falling back to auto-detect",
                    preferred,
                )

        # Auto-detect: find the best encoder, then map to the requested codec
        best = detect_best_encoder()

        # Derive vendor from the best encoder (e.g., h264_nvenc → nvidia)
        for vendor, encoders in _VENDOR_ENCODERS.items():
            if best in encoders.values():
                # Use this vendor's encoder for the requested codec
                vendor_encoder = encoders.get(self._codec)
                if vendor_encoder and _encoder_works(vendor_encoder):
                    logger.info(
                        "Auto-detected %s → using %s for codec %s",
                        vendor,
                        vendor_encoder,
                        self._codec,
                    )
                    return vendor_encoder
                break  # Vendor found but doesn't support this codec

        # No vendor match or vendor doesn't support the codec → software
        return _SOFTWARE_CODECS.get(self._codec, "libx264")

    @staticmethod
    def _choose_hwaccel(encoder_name: str) -> str:
        """Derive ffmpeg ``-hwaccel`` value from *encoder_name*."""
        if "nvenc" in encoder_name:
            return "cuda"
        if "vaapi" in encoder_name:
            return "vaapi"
        if "qsv" in encoder_name:
            return "qsv"
        return "auto"

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
