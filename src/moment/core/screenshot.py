"""Screenshot — capture and post-process screenshots.

Primary path: ``RecorderController.take_screenshot()`` sends SIGUSR1 to
gpu-screen-recorder, which writes a PNG.  This module provides the
**fallback** path (ffmpeg x11grab) and post-processing (crop, auto-name,
thumbnail generation).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec B404 — required for external tool invocation
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from moment.utils.ffmpeg import FFmpegError, find_ffmpeg
from moment.utils.subprocess import run_sandboxed
from moment.utils.system import ensure_dir

logger = logging.getLogger(__name__)

# Default screenshot directory
SCREENSHOT_DIR = os.path.expanduser("~/Pictures/Moment")

# Default image format
_DEFAULT_FORMAT = "png"


class ScreenshotError(RuntimeError):
    """Raised when screenshot capture fails."""


class Screenshot:
    """Handles screenshot capture (fallback) and post-processing.

    The primary capture path (SIGUSR1 → gpu-screen-recorder) is managed
    by :class:`~moment.core.recorder_controller.RecorderController`.
    This class provides:

    1. A fallback capture method using ``ffmpeg x11grab`` when the
       recorder is not available.
    2. Post-processing: auto-naming with timestamp, optional crop,
       thumbnail generation.
    """

    def __init__(
        self,
        output_dir: str | None = None,
        *,
        on_captured: Callable[[Path], None] | None = None,
    ) -> None:
        """Args:
            output_dir: Directory for screenshot output.
                Defaults to ``~/Pictures/Moment``.
            on_captured: Called as ``callback(path)`` when a screenshot
                is captured and post-processed.
        """
        self._output_dir = ensure_dir(output_dir or SCREENSHOT_DIR)
        self._on_captured = on_captured

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_fallback(self, *, label: str | None = None) -> Path:
        """Capture a screenshot using ffmpeg x11grab (fallback path).

        Args:
            label: Optional label for the filename.

        Returns:
            Path to the captured PNG.

        Raises:
            ScreenshotError: If capture fails.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name = f"screenshot_{timestamp}"
        if label:
            safe_label = label.replace(" ", "_").replace("/", "_")
            name = f"{name}_{safe_label}"

        output = self._output_dir / f"{name}.{_DEFAULT_FORMAT}"

        # Detect display and resolution
        raw_display = os.environ.get("DISPLAY", ":0.0")
        display = self._validate_display(raw_display)
        resolution = self._detect_resolution(display)

        try:
            find_ffmpeg()
        except FFmpegError as exc:
            raise ScreenshotError(f"ffmpeg not available: {exc}") from exc

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "x11grab",
            "-video_size", resolution,
            "-i", display,
            "-vframes", "1",
            str(output),
        ]

        logger.info("Fallback screenshot: %s", cmd)
        try:
            result = run_sandboxed(cmd, timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError(f"Screenshot capture timed out: {exc}") from exc
        if result.returncode != 0:
            raise ScreenshotError(
                f"Screenshot failed (code={result.returncode}): {result.stderr.strip()[-200:]}"
            )

        if not output.is_file() or output.stat().st_size == 0:
            raise ScreenshotError(f"Screenshot file missing or empty: {output}")

        logger.info("Screenshot captured: %s", output.name)
        if self._on_captured is not None:
            try:
                self._on_captured(output)
            except Exception as exc:
                logger.exception("on_captured callback error: %s", exc)

        return output

    def post_process(
        self,
        path: Path,
        *,
        crop: tuple[int, int, int, int] | None = None,
        generate_thumbnail: bool = True,
    ) -> Path:
        """Post-process a screenshot (crop, rename, thumbnail).

        Args:
            path: Path to the raw screenshot.
            crop: Optional ``(x, y, width, height)`` crop region.
            generate_thumbnail: Whether to generate a small thumbnail.

        Returns:
            Path to the processed screenshot.
        """
        if crop is not None:
            path = self._crop(path, crop)

        if generate_thumbnail:
            thumb_path = path.with_suffix(f".thumb{path.suffix}")
            self._generate_thumbnail(path, thumb_path)

        return path

    @property
    def output_dir(self) -> Path:
        """The screenshot output directory."""
        return self._output_dir

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_display(value: str) -> str:
        r"""Validate DISPLAY env var against ``^:[0-9]+(\.[0-9]+)?$``.

        Falls back to ``":0.0"`` on invalid values.
        """
        if re.fullmatch(r"^:[0-9]+(\.[0-9]+)?$", value):
            return value
        logger.warning(
            "Invalid DISPLAY value %r — falling back to :0.0", value
        )
        return ":0.0"

    @staticmethod
    def _detect_resolution(display: str) -> str:
        """Detect screen resolution via xrandr or fallback to 1920x1080."""
        try:
            # Try xdpyinfo first (most reliable on X11)
            result = subprocess.run(
                ["xdpyinfo"],
                capture_output=True,
                text=True,
                timeout=5,
            )  # nosec
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "dimensions:" in line:
                        # "  dimensions:    3840x2160 pixels (…)"
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            return parts[1]  # "3840x2160"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: ask xrandr for the primary output
        try:
            result = subprocess.run(
                ["xrandr"],
                capture_output=True,
                text=True,
                timeout=5,
            )  # nosec
            if result.returncode == 0:
                import re
                for line in result.stdout.splitlines():
                    if " connected" in line and "+0+0" in line:
                        m = re.search(r"(\d+x\d+)", line)
                        if m:
                            return m.group(1)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return "1920x1080"

    def _crop(self, path: Path, crop: tuple[int, int, int, int]) -> Path:
        """Crop the screenshot using ffmpeg."""
        x, y, w, h = crop
        output = path.with_stem(f"{path.stem}_cropped")

        find_ffmpeg()
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(path),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            str(output),
        ]
        result = run_sandboxed(cmd)
        if result.returncode != 0:
            logger.warning("Crop failed, returning original: %s", result.stderr.strip()[-200:])
            output.unlink(missing_ok=True)
            return path

        # Replace original with cropped
        path.unlink(missing_ok=True)
        output.rename(path)
        return path

    def _generate_thumbnail(self, source: Path, output: Path) -> None:
        """Generate a small thumbnail version."""
        try:
            find_ffmpeg()
            cmd = [
                "ffmpeg",
                "-y",
                "-i", str(source),
                "-vf", "scale=320:-1",
                "-q:v", "2",
                str(output),
            ]
            result = run_sandboxed(cmd, timeout=10)
            if result.returncode != 0:
                logger.warning("Thumbnail generation failed: %s", result.stderr.strip()[-200:])
        except (FileNotFoundError, subprocess.TimeoutExpired, FFmpegError) as exc:
            logger.warning("Thumbnail generation error: %s", exc)
