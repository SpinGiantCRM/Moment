"""Core data models — pure dataclasses and enums.

Absolutely **no GUI imports** allowed in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ClipStatus(Enum):
    """Processing state of a clip in the pipeline."""

    PENDING = auto()
    ENCODING = auto()
    DONE = auto()
    UPLOADING = auto()
    UPLOADED = auto()
    ERROR = auto()
    CORRUPT = auto()
    QUEUED = auto()


class ClipVisibility(Enum):
    """Visibility level for uploaded clips."""

    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class ClipType(Enum):
    """Kind of clip stored."""

    VIDEO = auto()
    SCREENSHOT = auto()
    IMPORTED = auto()


class TaskStatus(Enum):
    """Lifecycle state of a pipeline task."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TaskKind(Enum):
    """Type of work handled by the pipeline."""

    ENCODE = "encode"
    UPLOAD = "upload"
    THUMBNAIL = "thumbnail"
    IMPORT = "import"
    HEALTH_CHECK = "health_check"


# ---------------------------------------------------------------------------
# Primary dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Clip:
    """Represents a single captured clip."""

    id: str
    stem: str
    source_path: Path
    encoded_path: Path | None = None
    thumb_path: Path | None = None

    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration: float = 0.0
    file_size: int = 0
    video_codec: str = ""
    fps: float = 0.0
    resolution: tuple[int, int] = (0, 0)
    has_mic_audio: bool = False
    has_game_audio: bool = False

    title: str = ""
    game: str | None = None
    tags: list[str] = field(default_factory=list)
    folder: str | None = None
    favorite: bool = False

    status: ClipStatus = ClipStatus.PENDING
    error_message: str | None = None

    uploaded_at: datetime | None = None
    r2_url: str | None = None
    r2_path: str | None = None
    copy_count: int = 0
    visibility: ClipVisibility = ClipVisibility.PUBLIC

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None
    protect_from_retention: bool = False

    clip_type: ClipType = ClipType.VIDEO
    source_app: str | None = None
    original_filename: str | None = None

    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    watched_at: datetime | None = None
    watch_count: int = 0

    discord_user_id: str = ""


# ---------------------------------------------------------------------------
# Editing models
# ---------------------------------------------------------------------------

@dataclass
class SegmentEdit:
    """A segment of a clip with optional speed adjustment."""

    start: float
    end: float
    speed: float = 1.0


@dataclass
class FilterConfig:
    """A video filter to apply during encoding."""

    filter_name: str
    params: dict[str, float] = field(default_factory=dict)


@dataclass
class OverlayConfig:
    """A text or image overlay positioned on the video."""

    overlay_type: Literal["text", "image"]
    content: str
    position_x: float = 0.5  # 0.0–1.0 relative
    position_y: float = 0.5
    width: float | None = None  # relative
    height: float | None = None  # relative
    start_time: float | None = None  # seconds
    end_time: float | None = None  # seconds
    opacity: float = 1.0


@dataclass
class EditProfile:
    """Accumulated edits for a clip — persisted 1:1 with the clip."""

    clip_id: str
    trim_start: float | None = None
    trim_end: float | None = None
    split_points: list[float] = field(default_factory=list)
    segments: list[SegmentEdit] = field(default_factory=list)
    game_audio_volume: float = 1.0  # 0.0–2.0
    mic_audio_volume: float = 1.0  # 0.0–2.0
    filters: list[FilterConfig] = field(default_factory=list)
    overlays: list[OverlayConfig] = field(default_factory=list)
    merge_source_ids: list[str] | None = None
    edit_version: int = 1


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------

@dataclass
class Bookmark:
    """A point-of-interest marker within a session."""

    id: str
    session_stem: str
    offset_seconds: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    label: str | None = None


@dataclass
class Webhook:
    """Discord webhook configuration."""

    id: str
    url: str
    name: str = ""
    enabled: bool = True
    notify_on: list[str] = field(default_factory=list)
    per_game_filter: list[str] | None = None
    include_clip_url: bool = False


@dataclass
class WebhookLogEntry:
    """Record of a webhook delivery attempt."""

    id: str
    webhook_id: str
    clip_id: str
    delivered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True
    status_code: int = 200
    error_message: str | None = None


@dataclass
class ReviewCardConfig:
    """Per-game review card display settings."""

    enabled: bool = True
    size: Literal["small", "medium", "large"] = "medium"
    preview_duration: float = 15.0
    show_mini_player: bool = True
    show_game_name: bool = True
    show_duration: bool = True
    show_file_size: bool = True
    show_quality_badge: bool = True
    show_rename: bool = True
    show_trim: bool = True
    show_favorite: bool = True
    animation_style: Literal["slide", "fade", "scale"] = "slide"
    fade_thumbnail_if_short: bool = True


@dataclass
class GameProfile:
    """Per-game recording configuration."""

    id: str
    game_name: str
    display_name: str
    replay_duration: int = 30
    audio_config: dict | None = None
    capture_fps: int = 60
    encode_timing: str | None = None
    quality_preset: str | None = None
    pause_encode: bool = True
    pause_thumbnail: bool = True
    auto_tag: bool = True
    auto_open_editor: bool = True
    review_card: ReviewCardConfig | None = None
    min_duration: int = 30  # Minimum clip duration (seconds) to keep on game exit
    post_capture_action: Literal["card", "discard", "editor"] = "card"  # Action on game exit


@dataclass
class Tag:
    """A user-defined tag."""

    id: str
    name: str
    color: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Folder:
    """A user-defined folder for organising clips."""

    id: str
    name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(order=False)
class Task:
    """A unit of work for the pipeline."""

    id: str
    type: TaskKind
    priority: int = 0
    payload: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return NotImplemented
        return self.id < other.id
