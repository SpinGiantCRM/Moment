"""Tests for core.models — verify all dataclasses and enums."""

from __future__ import annotations

import uuid
from pathlib import Path

from moment.core.models import (
    Bookmark,
    Clip,
    ClipStatus,
    ClipType,
    ClipVisibility,
    EditProfile,
    Folder,
    GameProfile,
    OverlayConfig,
    ReviewCardConfig,
    SegmentEdit,
    Tag,
    Task,
    TaskKind,
    TaskStatus,
    Webhook,
    WebhookLogEntry,
)


class TestEnums:
    def test_clip_status_has_all_states(self) -> None:
        names = {s.name for s in ClipStatus}
        assert names >= {
            "PENDING",
            "ENCODING",
            "DONE",
            "UPLOADING",
            "UPLOADED",
            "ERROR",
            "CORRUPT",
            "QUEUED",
        }

    def test_clip_visibility_values(self) -> None:
        assert ClipVisibility.PUBLIC.value == "public"
        assert ClipVisibility.UNLISTED.value == "unlisted"
        assert ClipVisibility.PRIVATE.value == "private"

    def test_clip_type(self) -> None:
        assert ClipType.VIDEO.name == "VIDEO"
        assert ClipType.SCREENSHOT.name == "SCREENSHOT"
        assert ClipType.IMPORTED.name == "IMPORTED"

    def test_task_status(self) -> None:
        names = {s.name for s in TaskStatus}
        assert names >= {"PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}

    def test_task_kind_values(self) -> None:
        assert TaskKind.ENCODE.value == "encode"
        assert TaskKind.UPLOAD.value == "upload"


class TestClip:
    def test_minimal_clip(self) -> None:
        clip = Clip(
            id=str(uuid.uuid4()),
            stem="2026-05-01_12-00-00",
            source_path=Path("/tmp/test.mkv"),
        )
        assert clip.status == ClipStatus.PENDING
        assert clip.tags == []
        assert clip.favorite is False

    def test_clip_defaults(self) -> None:
        clip = Clip(id="abc", stem="test", source_path=Path("test.mkv"))
        assert clip.duration == 0.0
        assert clip.file_size == 0
        assert clip.copy_count == 0
        assert clip.watch_count == 0
        assert clip.protect_from_retention is False
        assert clip.favorite is False
        assert clip.visibility == ClipVisibility.PUBLIC
        assert clip.clip_type == ClipType.VIDEO

    def test_clip_full_fields(self) -> None:
        clip = Clip(
            id="abc123",
            stem="2026-05-01_12-00-00",
            source_path=Path("/tmp/test.mkv"),
            encoded_path=Path("/tmp/test.mp4"),
            thumb_path=Path("/tmp/test.jpg"),
            duration=25.5,
            file_size=40_000_000,
            video_codec="h264",
            fps=60.0,
            resolution=(1920, 1080),
            has_mic_audio=True,
            has_game_audio=True,
            title="Epic Clip",
            game="cs2",
            tags=["frag", "ace"],
            folder="Highlights",
            favorite=True,
            status=ClipStatus.UPLOADED,
            r2_url="https://r2.example.com/test.mp4",
            r2_path="bucket/test.mp4",
            copy_count=3,
            visibility=ClipVisibility.PUBLIC,
            clip_type=ClipType.VIDEO,
        )
        assert clip.id == "abc123"
        assert clip.title == "Epic Clip"
        assert clip.tags == ["frag", "ace"]
        assert clip.folder == "Highlights"
        assert clip.favorite is True
        assert clip.status == ClipStatus.UPLOADED
        assert clip.visibility == ClipVisibility.PUBLIC


class TestEditProfile:
    def test_defaults(self) -> None:
        ep = EditProfile(clip_id="clip1")
        assert ep.clip_id == "clip1"
        assert ep.trim_start is None
        assert ep.game_audio_volume == 1.0
        assert ep.mic_audio_volume == 1.0
        assert ep.segments == []
        assert ep.edit_version == 1

    def test_with_segments(self) -> None:
        ep = EditProfile(
            clip_id="clip2",
            segments=[SegmentEdit(start=5.0, end=10.0, speed=2.0)],
        )
        assert len(ep.segments) == 1
        assert ep.segments[0].speed == 2.0

    def test_with_overlay(self) -> None:
        ep = EditProfile(
            clip_id="clip3",
            overlays=[
                OverlayConfig(
                    overlay_type="text",
                    content="Hello",
                    position_x=0.5,
                    position_y=0.1,
                ),
            ],
        )
        assert len(ep.overlays) == 1
        assert ep.overlays[0].content == "Hello"


class TestSupportingModels:
    def test_bookmark(self) -> None:
        bm = Bookmark(id="b1", session_stem="session1", offset_seconds=12.5)
        assert bm.offset_seconds == 12.5
        assert bm.label is None

    def test_webhook(self) -> None:
        wh = Webhook(id="w1", url="https://discord.com/webhook", name="My Hook")
        assert wh.enabled is True
        assert wh.notify_on == []
        assert wh.per_game_filter is None

    def test_webhook_log_entry(self) -> None:
        entry = WebhookLogEntry(
            id="wl1",
            webhook_id="w1",
            clip_id="c1",
            success=False,
            status_code=500,
        )
        assert entry.success is False
        assert entry.status_code == 500

    def test_game_profile(self) -> None:
        gp = GameProfile(id="gp1", game_name="cs2", display_name="Counter-Strike 2")
        assert gp.replay_duration == 30
        assert gp.capture_fps == 60
        assert gp.pause_encode is True
        assert gp.auto_tag is True
        assert gp.review_card is None

    def test_game_profile_with_review_card(self) -> None:
        rc = ReviewCardConfig(size="large", preview_duration=30.0)
        gp = GameProfile(id="gp1", game_name="cs2", display_name="CS2", review_card=rc)
        assert gp.review_card is not None
        assert gp.review_card.size == "large"
        assert gp.review_card.preview_duration == 30.0

    def test_tag(self) -> None:
        t = Tag(id="t1", name="frag", color="#ff0000")
        assert t.name == "frag"
        assert t.color == "#ff0000"

    def test_folder(self) -> None:
        f = Folder(id="f1", name="Highlights")
        assert f.name == "Highlights"

    def test_task(self) -> None:
        t = Task(id="t1", type=TaskKind.ENCODE, priority=5)
        assert t.type == TaskKind.ENCODE
        assert t.status == TaskStatus.PENDING
        assert t.retry_count == 0
        assert t.max_retries == 3

    def test_task_ordering(self) -> None:
        t1 = Task(id="a", type=TaskKind.ENCODE)
        t2 = Task(id="b", type=TaskKind.ENCODE)
        assert t1 < t2  # alphabetical by id
        assert not (t2 < t1)

    def test_task_lt_not_task_returns_not_implemented(self) -> None:
        t = Task(id="t1", type=TaskKind.ENCODE)
        result = t.__lt__("not a task")  # type: ignore[arg-type]
        assert result is NotImplemented

    def test_health_check_task_kind(self) -> None:
        assert TaskKind.HEALTH_CHECK.value == "health_check"

    def test_import_task_kind(self) -> None:
        assert TaskKind.IMPORT.value == "import"

    def test_thumbnail_task_kind(self) -> None:
        assert TaskKind.THUMBNAIL.value == "thumbnail"
