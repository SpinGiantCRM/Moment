"""Recording path discovery and bulk import for the first-run wizard.

Absolutely **no GUI imports** allowed in this module.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from moment.core.models import Clip, ClipStatus, ClipType
from moment.utils.system import ensure_dir, sanitize_stem

if TYPE_CHECKING:
    from moment.core.config import Config
    from moment.core.store import Store

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mkv", ".mp4", ".mov"})


class RecordingCandidate(TypedDict):
    """A directory that may contain importable recordings."""

    source_dir: str
    encoded_dir: str
    clip_count: int
    clip_count_new: int
    label: str


def count_video_files(directory: Path, *, recursive: bool = True) -> int:
    """Count video files under *directory*.

    Args:
        directory: Root directory to scan.
        recursive: When ``True``, walk subdirectories.

    Returns:
        Number of matching video files found.
    """
    if not directory.is_dir():
        return 0

    count = 0
    if recursive:
        for root, _dirs, files in os.walk(directory):
            for name in files:
                if Path(name).suffix.lower() in VIDEO_EXTENSIONS:
                    count += 1
    else:
        for child in directory.iterdir():
            if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                count += 1
    return count


def _iter_video_files(directory: Path) -> list[Path]:
    """Return all video file paths under *directory* (recursive)."""
    if not directory.is_dir():
        return []
    paths: list[Path] = []
    for root, _dirs, files in os.walk(directory):
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() in VIDEO_EXTENSIONS and path.is_file():
                paths.append(path)
    return paths


def _existing_source_paths(store: "Store") -> set[str]:
    """Return resolved source paths already present in the database."""
    rows = store._read_conn.execute(
        "SELECT source_path FROM clips WHERE deleted_at IS NULL AND source_path != ''"
    ).fetchall()
    result: set[str] = set()
    for row in rows:
        raw = row["source_path"]
        if not raw:
            continue
        try:
            result.add(str(Path(raw).resolve()))
        except OSError:
            result.add(str(raw))
    return result


def _candidate_dirs(config: "Config | None") -> list[tuple[Path, str]]:
    """Priority-ordered (path, label) pairs to scan for recordings."""
    home = Path.home()
    videos = home / "Videos"
    candidates: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def _add(path: Path, label: str) -> None:
        key = str(path.expanduser().resolve()) if path.exists() else str(path.expanduser())
        if key in seen:
            return
        seen.add(key)
        candidates.append((path.expanduser(), label))

    if videos.is_dir():
        for child in sorted(videos.iterdir()):
            if child.is_dir() and child.name.startswith("gsr"):
                _add(child, f"GSR — {child.name}")

    _add(videos / "GPU-Screen-Recorder", "GPU Screen Recorder")
    _add(videos / "Moment", "Moment recordings")
    _add(videos / "OBS", "OBS Studio")
    for clip_dir in ("Clips", "clips"):
        base = videos / clip_dir
        _add(base, clip_dir)
        _add(base / "source", f"{clip_dir}/source")

    _add(videos / "Recordings", "Recordings")
    _add(videos / "Recordings" / "source", "Recordings/source")
    _add(videos / "Screen Recordings", "Screen Recordings")
    _add(videos / "Screen Recordings" / "source", "Screen Recordings/source")

    encoded_default = home / ".local/share/moment/encoded"
    _add(encoded_default, "Encoded output")

    if config is not None:
        configured = config.get("path_recordings_dir")
        if isinstance(configured, str) and configured.strip():
            _add(Path(configured), "Configured recordings folder")

    return candidates


def discover_recording_paths(
    config: "Config | None" = None,
    store: "Store | None" = None,
) -> list[RecordingCandidate]:
    """Scan common recording locations and return import candidates.

    Args:
        config: Optional config for path overrides.
        store: Optional store to subtract already-imported clips.

    Returns:
        Candidates with ``clip_count`` (total videos) and
        ``clip_count_new`` (not yet in the database).
    """
    existing = _existing_source_paths(store) if store is not None else set()
    default_encode = (
        config.get_path("encode_dir")
        if config is not None
        else os.path.expanduser("~/.local/share/moment/encoded")
    )

    results: list[RecordingCandidate] = []
    for source_path, label in _candidate_dirs(config):
        if not source_path.is_dir():
            continue

        all_files = _iter_video_files(source_path)
        clip_count = len(all_files)
        if clip_count == 0:
            continue

        clip_count_new = 0
        for path in all_files:
            try:
                resolved = str(path.resolve())
            except OSError:
                resolved = str(path)
            if resolved not in existing:
                clip_count_new += 1

        results.append(
            RecordingCandidate(
                source_dir=str(source_path),
                encoded_dir=default_encode,
                clip_count=clip_count,
                clip_count_new=clip_count_new,
                label=label,
            )
        )

    return results


def import_recordings_from_dirs(
    store: "Store",
    source_dirs: list[Path | str],
) -> tuple[int, int]:
    """Import video files from *source_dirs* into the clip database.

    Files are referenced in-place (not copied).  Already-imported paths
    (matching ``source_path``) are skipped.

    Args:
        store: Application store.
        source_dirs: One or more directories to walk recursively.

    Returns:
        ``(imported, failed)`` — counts of newly inserted clips and files
        that could not be imported.
    """
    existing = _existing_source_paths(store)
    imported = 0
    failed = 0

    for raw_dir in source_dirs:
        directory = Path(raw_dir)
        for path in _iter_video_files(directory):
            try:
                resolved = str(path.resolve())
            except OSError:
                resolved = str(path)
            if resolved in existing:
                continue

            try:
                stat = path.stat()
            except OSError as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)
                failed += 1
                continue

            if stat.st_size == 0:
                continue

            recorded_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            stem = sanitize_stem(path.stem)

            clip = Clip(
                id=str(uuid.uuid4()),
                stem=stem,
                source_path=path,
                recorded_at=recorded_at,
                file_size=stat.st_size,
                title=stem,
                status=ClipStatus.DONE,
                clip_type=ClipType.IMPORTED,
                source_app="import_wizard",
                original_filename=path.name,
            )
            try:
                store.insert_clip(clip)
            except Exception as exc:
                logger.warning("Failed to import %s: %s", path, exc)
                failed += 1
                continue
            existing.add(resolved)
            imported += 1

    return imported, failed


def ensure_source_and_encode_dirs(
    source_dir: Path | str,
    encode_dir: Path | str,
) -> tuple[Path, Path]:
    """Create source and encode directories if missing.

    Args:
        source_dir: Recordings / source folder path.
        encode_dir: Encoded output folder path.

    Returns:
        Resolved paths for both directories.
    """
    return ensure_dir(source_dir), ensure_dir(encode_dir)
