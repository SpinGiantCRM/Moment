"""Data migrations — legacy JSON import, directory renames, etc."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from moment.core.models import Clip, ClipStatus, ClipVisibility
from moment.core.repositories.base import parse_datetime, parse_enum

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

_OLD_DB_DIR = os.path.expanduser("~/.config/clip-tray")
_OLD_DATA_DIR = os.path.expanduser("~/.local/share/clip-tray")
_DEFAULT_DB_DIR = os.path.expanduser("~/.config/moment")
_DEFAULT_DATA_DIR = os.path.expanduser("~/.local/share/moment")
OLD_JSON_PATH = os.path.join(_DEFAULT_DB_DIR, "clips.json")


def migrate_old_dirs(
    old_db_dir: str | None = None,
    old_data_dir: str | None = None,
    new_db_dir: str | None = None,
    new_data_dir: str | None = None,
) -> None:
    """Rename legacy clip-tray directories to moment."""
    _old_db = old_db_dir or _OLD_DB_DIR
    _old_data = old_data_dir or _OLD_DATA_DIR
    _new_db = new_db_dir or _DEFAULT_DB_DIR
    _new_data = new_data_dir or _DEFAULT_DATA_DIR
    for old, new in ((_old_db, _new_db), (_old_data, _new_data)):
        if os.path.isdir(old) and not os.path.isdir(new):
            try:
                os.rename(old, new)
                logger.info("Migration: Renamed %s → %s", old, new)
            except OSError:
                logger.warning("Could not rename %s → %s", old, new)


def migrate_from_json(store: "Store", old_path: Path) -> int:
    """Import clips from legacy clips.json into SQLite."""
    if not old_path.is_file():
        return 0

    row = store._read_conn.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()
    if row and row["cnt"] > 0:
        logger.info("%s found but DB already has data; renaming to .bak", old_path)
        try:
            os.rename(str(old_path), str(old_path) + ".bak")
        except OSError as exc:
            logger.warning("Could not rename %s: %s", old_path, exc)
        return 0

    logger.info("Migrating from %s → SQLite …", old_path)
    count = 0
    try:
        with open(old_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not parse %s: %s", old_path, exc)
        return 0

    entries: list[dict] = data if isinstance(data, list) else data.get("clips", [])
    for entry in entries:
        try:
            clip = Clip(
                id=entry.get("id", str(uuid.uuid4())),
                stem=entry.get("stem", ""),
                source_path=Path(entry.get("source_path", "")),
                recorded_at=(parse_datetime(entry.get("recorded_at"))
                             or datetime.now(timezone.utc)),
                duration=float(entry.get("duration", 0)),
                file_size=int(entry.get("file_size", 0)),
                title=entry.get("title", ""),
                game=entry.get("game"),
                folder=entry.get("folder"),
                favorite=bool(entry.get("favorite", False)),
                status=parse_enum(
                    entry.get("status"), ClipStatus, ClipStatus.DONE,
                ),
                visibility=parse_enum(
                    entry.get("visibility"), ClipVisibility, ClipVisibility.PUBLIC,
                ),
            )
            store.insert_clip(clip)
            count += 1
        except Exception as exc:
            logger.warning("Skipping corrupt clip during migration: %s", exc)

    try:
        os.rename(str(old_path), str(old_path) + ".bak")
        logger.info("Migration complete: %d clips imported", count)
    except OSError as exc:
        logger.warning("Could not rename %s: %s", old_path, exc)

    return count
