"""Tests for core/pipeline.py — task queue, worker threads, game-aware pausing."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.config import Config
from moment.core.encoder import Encoder, EncoderError
from moment.core.models import (
    Clip,
    ClipStatus,
    EditProfile,
    Task,
    TaskKind,
    TaskStatus,
)
from moment.core.pipeline import Pipeline
from moment.core.store import Store
from moment.core.thumbnail import Thumbnailer
from moment.core.uploader import Uploader, UploaderError
from moment.utils.ffmpeg import parse_fps


def _make_clip(store: Store, *, id: str, stem: str = "", source_path: str = "", **kwargs: object) -> Clip:
    clip = Clip(
        id=id,
        stem=stem or id,
        source_path=Path(source_path or f"/tmp/{id}.mkv"),
        status=ClipStatus.PENDING,
        **{k: v for k, v in kwargs.items() if k not in ("id", "stem", "source_path", "status")},
    )
    store.insert_clip(clip)
    return clip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestParseFps:
    def test_simple_float(self) -> None:
        assert parse_fps("60") == 60.0

    def test_fraction(self) -> None:
        assert parse_fps("30000/1001") == pytest.approx(29.97, rel=0.01)

    def test_invalid(self) -> None:
        assert parse_fps("not_a_number") == 0.0

    def test_zero_denominator(self) -> None:
        assert parse_fps("60/0") == 0.0


# ---------------------------------------------------------------------------
# Pipeline initialisation
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_pipeline_creates_workers(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        assert len(p._workers) > 0
        p.shutdown()

    def test_paused_initially_false(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        assert not p.paused
        p.shutdown()

    def test_custom_worker_counts(self, store: Store) -> None:
        p = Pipeline(
            store, Config(store._db_path),
            encode_workers=2, upload_workers=3, thumbnail_workers=1,
        )
        assert len(p._workers) == 6
        p.shutdown()

    def test_injectable_components(self, store: Store) -> None:
        encoder = Encoder(codec="h264")
        uploader = Uploader(remote="test", bucket="test")
        thumbnailer = Thumbnailer(thumb_dir="/tmp/thumbs")

        p = Pipeline(
            store, Config(store._db_path),
            encoder=encoder, uploader=uploader, thumbnailer=thumbnailer,
        )
        assert p._encoder is encoder
        assert p._uploader is uploader
        assert p._thumbnailer is thumbnailer
        p.shutdown()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

class TestEnqueue:
    def test_enqueue_adds_to_store(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        task = Task(id="t1", type=TaskKind.ENCODE, priority=0)
        p.enqueue(task)
        p.shutdown()

        # Task should be in the store
        stored = store.get_pending_tasks(limit=10)
        assert any(t.id == "t1" for t in stored)

    def test_enqueue_sets_pending_status(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        task = Task(id="t2", type=TaskKind.THUMBNAIL)
        p.enqueue(task)
        assert task.status == TaskStatus.PENDING
        p.shutdown()


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------

class TestPauseResume:
    def test_pause_sets_flag(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p.pause()
        assert p.paused
        p.shutdown()

    def test_resume_clears_flag(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p.pause()
        p.resume()
        assert not p.paused
        p.shutdown()


# ---------------------------------------------------------------------------
# Status reporting
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_idle_when_no_work(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        status = p.get_status()
        assert status == "Idle"
        p.shutdown()

    def test_paused_status(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p.pause()
        status = p.get_status()
        assert "(paused)" in status
        p.shutdown()

    def test_active_tasks_in_status(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p._inc_counter("encode")
        status = p.get_status()
        assert "Encoding" in status
        p._dec_counter("encode")
        p.shutdown()


# ---------------------------------------------------------------------------
# Encode processing (mocked)
# ---------------------------------------------------------------------------

class TestProcessEncode:
    def test_processes_encode_successfully(self, store: Store) -> None:
        clip = _make_clip(store, id="enc-1", stem="enc_test_1")

        encoder = Encoder(codec="h264")
        encoded: list[str] = []
        p = Pipeline(
            store, Config(store._db_path),
            encoder=encoder,
            on_clip_encoded=lambda stem: encoded.append(stem),
        )

        with (
            patch.object(encoder, "encode", return_value=Path("/tmp/enc_test_1.mp4")),
            patch("moment.core.pipeline.ffprobe", return_value={"format": {"duration": "10.0"}, "streams": []}),
        ):
            task = Task(
                id="task-enc-1",
                type=TaskKind.ENCODE,
                payload={"clip_id": "enc-1"},
            )
            p._process_encode(task)

        # Clip should be updated to DONE
        updated = store.get_clip("enc-1")
        assert updated is not None and updated.status == ClipStatus.DONE
        assert len(encoded) == 1
        p.shutdown()

    def test_processes_encode_with_missing_clip(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        task = Task(
            id="task-bad",
            type=TaskKind.ENCODE,
            payload={"clip_id": "nonexistent"},
        )
        p._process_encode(task)
        p.shutdown()

    def test_processes_encode_failure(self, store: Store) -> None:
        clip = _make_clip(store, id="enc-fail", stem="enc_fail")

        encoder = Encoder(codec="h264")
        errors: list[tuple[str, str]] = []
        p = Pipeline(
            store, Config(store._db_path),
            encoder=encoder,
            on_clip_errored=lambda stem, err: errors.append((stem, err)),
        )

        with (
            patch.object(encoder, "encode", side_effect=EncoderError("GPU error")),
            patch("moment.core.pipeline.ffprobe", return_value={"format": {"duration": "10.0"}, "streams": []}),
        ):
            task = Task(id="task-fail", type=TaskKind.ENCODE, payload={"clip_id": "enc-fail"})
            p._process_encode(task)

        updated = store.get_clip("enc-fail")
        assert updated is not None and updated.status == ClipStatus.ERROR
        assert len(errors) == 1
        p.shutdown()


# ---------------------------------------------------------------------------
# Upload processing (mocked)
# ---------------------------------------------------------------------------

class TestProcessUpload:
    def test_processes_upload_successfully(self, store: Store) -> None:
        clip = _make_clip(
            store, id="up-1", stem="up_test_1",
            encoded_path="/tmp/up_test_1.mp4",
        )
        # Create the actual file
        Path("/tmp/up_test_1.mp4").write_bytes(b"fake video")

        uploader = Uploader(remote="test", bucket="test")
        uploaded: list[tuple[str, str]] = []
        p = Pipeline(
            store, Config(store._db_path),
            uploader=uploader,
            on_clip_uploaded=lambda stem, url: uploaded.append((stem, url)),
        )

        with patch.object(uploader, "upload", return_value="https://cdn.example.com/up_test_1.mp4"):
            task = Task(
                id="task-up-1",
                type=TaskKind.UPLOAD,
                payload={"clip_id": "up-1", "path": "/tmp/up_test_1.mp4"},
            )
            p._process_upload(task)

        updated = store.get_clip("up-1")
        assert updated is not None and updated.status == ClipStatus.UPLOADED
        assert updated.r2_url == "https://cdn.example.com/up_test_1.mp4"
        assert len(uploaded) == 1
        p.shutdown()

    def test_processes_upload_failure(self, store: Store) -> None:
        clip = _make_clip(store, id="up-fail", stem="up_fail", encoded_path="/tmp/up_fail.mp4")
        Path("/tmp/up_fail.mp4").write_bytes(b"fake video")

        uploader = Uploader(remote="test", bucket="test")
        errors: list[tuple[str, str]] = []
        p = Pipeline(
            store, Config(store._db_path),
            uploader=uploader,
            on_clip_errored=lambda stem, err: errors.append((stem, err)),
        )

        with patch.object(uploader, "upload", side_effect=UploaderError("Network error")):
            task = Task(
                id="task-up-fail",
                type=TaskKind.UPLOAD,
                payload={"clip_id": "up-fail", "path": "/tmp/up_fail.mp4"},
            )
            p._process_upload(task)

        updated = store.get_clip("up-fail")
        assert updated is not None and updated.status == ClipStatus.ERROR
        p.shutdown()

    def test_processes_upload_missing_file(self, store: Store) -> None:
        _make_clip(store, id="up-nofile", stem="up_nofile")

        p = Pipeline(store, Config(store._db_path))
        task = Task(
            id="task-up-nofile",
            type=TaskKind.UPLOAD,
            payload={"clip_id": "up-nofile", "path": "/tmp/does_not_exist.mp4"},
        )
        p._process_upload(task)
        p.shutdown()


# ---------------------------------------------------------------------------
# Thumbnail processing (mocked)
# ---------------------------------------------------------------------------

class TestProcessThumbnail:
    def test_processes_thumbnail_successfully(self, store: Store) -> None:
        clip = _make_clip(store, id="th-1", stem="th_test_1")

        thumbnailer = Thumbnailer(thumb_dir="/tmp/thumbs")
        p = Pipeline(
            store, Config(store._db_path),
            thumbnailer=thumbnailer,
        )

        with patch.object(thumbnailer, "generate", return_value=Path("/tmp/thumbs/th_test_1.jpg")):
            task = Task(
                id="task-th-1",
                type=TaskKind.THUMBNAIL,
                payload={"clip_id": "th-1"},
            )
            p._process_thumbnail(task)

        updated = store.get_clip("th-1")
        assert updated is not None and updated.thumb_path is not None
        p.shutdown()

    def test_processes_thumbnail_missing_clip(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        task = Task(
            id="task-th-bad",
            type=TaskKind.THUMBNAIL,
            payload={"clip_id": "nonexistent"},
        )
        p._process_thumbnail(task)
        p.shutdown()


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_stops_workers(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p.shutdown()
        # All workers should have been joined
        for w in p._workers:
            assert not w.is_alive()

    def test_multiple_shutdowns_not_harmful(self, store: Store) -> None:
        p = Pipeline(store, Config(store._db_path))
        p.shutdown()
        p.shutdown()  # Should be safe


# ---------------------------------------------------------------------------
# Status timer
# ---------------------------------------------------------------------------

class TestStatusTimer:
    def test_status_callback_called(self, store: Store) -> None:
        statuses: list[str] = []
        p = Pipeline(
            store, Config(store._db_path),
            on_status=lambda s: statuses.append(s),
        )
        # Initial status is emitted immediately
        time.sleep(0.2)
        assert len(statuses) >= 1
        p.shutdown()
