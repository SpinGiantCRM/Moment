"""Import / export — external clip import and batch export.

Handles importing arbitrary media files into the clip library (with optional
re-encode) and exporting encoded clips to a destination folder.

Absolutely **no GUI imports** allowed in this module.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from moment.core.encoder import Encoder, EncoderError
from moment.core.models import Clip, ClipStatus, ClipType
from moment.core.store import Store
from moment.core.thumbnail import Thumbnailer
from moment.utils.ffmpeg import FFmpegError, parse_fps, probe as ffprobe
from moment.utils.system import ensure_dir, sanitize_stem

logger = logging.getLogger(__name__)

# Preset definitions
_PRESETS: dict[str, dict[str, object]] = {
    "game": {
        "label": "Game Mode",
        "codec": "h264",
        "quality": 23,
        "description": "Fast H.264 NVENC, high quality — best for sharing clips",
    },
    "archive": {
        "label": "Archive Mode",
        "codec": "h265",
        "quality": 28,
        "description": "HEVC, smaller files — best for long-term storage",
    },
    "streaming": {
        "label": "Streaming Mode",
        "codec": "h264",
        "quality": 30,
        "description": "H.264, lower bitrate — best for streaming platforms",
    },
}

# Default clips directory for imported files
CLIPS_DIR = Path.home() / "Videos"


class ImportError(Exception):
    """Raised when an import operation fails."""


class ImportExport:
    """Handles external clip imports and batch exports."""

    def __init__(self, store: Store, *, thumbnailer: Thumbnailer | None = None) -> None:
        """Args:
            store: The application store instance.
            thumbnailer: Optional Thumbnailer instance (created if not provided).
        """
        self._store = store
        self._thumbnailer = thumbnailer

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_file(
        self,
        path: Path,
        *,
        copy: bool = True,
        profile: Literal["game", "archive", "streaming"] = "game",
        re_encode: bool = False,
        game: str | None = None,
        tags: list[str] | None = None,
    ) -> Clip:
        """Import a media file into the clip library.

        Steps:
            1. Optionally copy the file into the clips directory.
            2. Probe metadata with ffprobe.
            3. Generate thumbnail.
            4. Insert a new :class:`Clip` row into the store.
            5. Optionally re-encode (iff *re_encode* is ``True``).

        Args:
            path: Source media file to import.
            copy: If ``True`` (default), copy the file into the clips
                directory.  If ``False``, reference it in-place.
            profile: Encoding preset (``"game"``, ``"archive"``, ``"streaming"``).
            re_encode: If ``True``, also transcode via the encode pipeline.
            game: Optional game name tag.
            tags: Optional list of tags for the new clip.

        Returns:
            The newly created :class:`Clip`.

        Raises:
            ImportError: If the source file is missing, unreadable, or
                ffprobe fails.
        """
        src = Path(path)
        if not src.is_file():
            raise ImportError(f"Source file not found: {src}")
        if src.stat().st_size == 0:
            raise ImportError(f"Source file is empty: {src}")

        stem = sanitize_stem(src.stem)
        original_filename = src.name
        target_path = src

        # Copy into clips directory
        if copy:
            dest_dir = Path(CLIPS_DIR)
            ensure_dir(dest_dir)
            dest = dest_dir / src.name
            # Avoid overwriting: append (1), (2), etc.
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem} ({counter}){src.suffix}"
                counter += 1
            shutil.copy2(src, dest)
            target_path = dest
            logger.info("Copied %s → %s", src, dest)

        # Probe metadata
        probe_data: dict = {}
        try:
            probe_data = ffprobe(target_path)
        except FFmpegError as exc:
            if copy and target_path != src:
                try:
                    os.unlink(target_path)
                except OSError:
                    pass
            raise ImportError(f"ffprobe failed for {target_path}: {exc}") from exc

        fmt = probe_data.get("format", {})
        duration = float(fmt.get("duration", 0))

        video_stream = next(
            (s for s in probe_data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if video_stream is None:
            if copy and target_path != src:
                try:
                    os.unlink(target_path)
                except OSError:
                    pass
            raise ImportError(f"No video stream found in {target_path}")

        video_codec = video_stream.get("codec_name", "")
        fps_str = video_stream.get("r_frame_rate", "0/1")
        fps = parse_fps(fps_str)
        resolution = (video_stream.get("width", 0), video_stream.get("height", 0))

        audio_streams = [s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"]
        has_game_audio = len(audio_streams) > 0
        has_mic_audio = False  # Cannot determine mic track from generic import

        file_size = target_path.stat().st_size

        # Generate thumbnail
        thumb_path: Path | None = None
        try:
            thumbnailer = self._thumbnailer or Thumbnailer()
            # Create a temporary clip object for the thumbnailer
            temp_clip = Clip(
                id=str(uuid.uuid4()),
                stem=stem,
                source_path=target_path,
                duration=duration,
            )
            thumb_path = thumbnailer.generate(temp_clip)
        except Exception:
            logger.warning("Thumbnail generation failed for import %s", stem, exc_info=True)

        # Create clip
        clip = Clip(
            id=str(uuid.uuid4()),
            stem=stem,
            source_path=target_path,
            thumb_path=thumb_path,
            recorded_at=datetime.now(timezone.utc),
            duration=duration,
            file_size=file_size,
            video_codec=video_codec,
            fps=fps,
            resolution=resolution,
            has_game_audio=has_game_audio,
            has_mic_audio=has_mic_audio,
            title=stem,
            game=game,
            tags=tags or [],
            status=ClipStatus.DONE,
            clip_type=ClipType.IMPORTED,
            source_app="import",
            original_filename=original_filename,
        )

        clip = self._store.insert_clip(clip)

        # Re-encode if requested
        if re_encode:
            preset = _PRESETS.get(profile, _PRESETS["game"])
            codec = str(preset["codec"])
            quality = int(preset["quality"])
            try:
                encoder = Encoder(codec=codec, quality=quality)
                encoded_path = encoder.encode(clip)
                clip.encoded_path = encoded_path
                clip.status = ClipStatus.ENCODING
                self._store.update_clip(clip)
            except EncoderError as exc:
                logger.error("Re-encode failed for import %s: %s", stem, exc)

        logger.info("Imported %s as clip %s", original_filename, clip.id)
        return clip

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_clips(self, clip_ids: list[str], dest: Path) -> int:
        """Copy encoded clip files to a destination folder.

        Preserves the original filename for each clip.  Clips without an
        encoded file are skipped.

        Args:
            clip_ids: List of clip IDs to export.
            dest: Destination directory (created if it does not exist).

        Returns:
            Number of files successfully copied.
        """
        dest = Path(dest)
        ensure_dir(dest)
        count = 0

        for cid in clip_ids:
            clip = self._store.get_clip(cid)
            if clip is None:
                logger.warning("Export: clip %s not found — skipping", cid)
                continue

            src = clip.encoded_path
            if src is None or not src.is_file():
                logger.warning("Export: clip %s has no encoded file — skipping", cid)
                continue

            out = dest / src.name
            try:
                shutil.copy2(src, out)
                count += 1
                logger.info("Exported %s → %s", src.name, dest)
            except OSError as exc:
                logger.error("Export failed for %s: %s", src.name, exc)

        return count

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    @staticmethod
    def list_presets() -> dict[str, dict[str, object]]:
        """Return the available import presets."""
        return dict(_PRESETS)

