"""Tests for core/pipeline.py — task queue and worker threads."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.config import Config
from moment.core.models import Clip, ClipStatus, Task, TaskKind, TaskStatus
from moment.core.pipeline import STATUS_INTERVAL, Pipeline
from moment.core.store import Store
from tests.conftest import wait_until
pytestmark = [pytest.mark.integration]


@pytest.fixture

def tmp_db_for_config() -> str:
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db", prefix="pipeline_config_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        for sfx in ("", "-wal", "-shm"):
            try: os.unlink(path + sfx)
            except FileNotFoundError: pass
    except FileNotFoundError:
        pass

@pytest.fixture
def config(tmp_db_for_config: str) -> Config:
    return Config(db_path=tmp_db_for_config)

@pytest.fixture
def pipeline(store: Store, config: Config) -> Pipeline:
    return Pipeline(
        store=store,
        config=config,
        encode_workers=0,  # no real workers in tests
        upload_workers=0,
        thumbnail_workers=0,
    )

class TestInitialization:
    def test_default_state(self, pipeline: Pipeline) -> None:
        assert pipeline.paused is False
        assert pipeline.get_status() == "Idle"

    def test_start_creates_workers(self, store: Store, config: Config) -> None:
        p = Pipeline(store=store, config=config, encode_workers=1, upload_workers=1, thumbnail_workers=1)
        p.start()
        assert len(p._workers) == 3
        p.shutdown()

    def test_double_start_raises(self, pipeline: Pipeline) -> None:
        pipeline.start()
        with pytest.raises(RuntimeError, match="already"):
            pipeline.start()
        pipeline.shutdown()

class TestEnqueue:
    def test_enqueue_adds_to_queue(self, pipeline: Pipeline) -> None:
        task = Task(id=str(uuid.uuid4()), type=TaskKind.ENCODE, priority=5, payload={"clip_id": "c1"})
        pipeline.enqueue(task)
        assert pipeline._queue.qsize() == 1

    def test_enqueue_saves_to_store(self, pipeline: Pipeline) -> None:
        task = Task(id="task-save", type=TaskKind.THUMBNAIL, payload={"clip_id": "c1"})
        pipeline.enqueue(task)
        pending = pipeline._store.get_pending_tasks()
        assert any(t.id == "task-save" for t in pending)

    def test_enqueue_task_queue_full(self, pipeline: Pipeline) -> None:
        # Fill the queue to max
        pipeline._queue = MagicMock()
        pipeline._queue.put_nowait.side_effect = [None, None, __import__("queue").Full()]
        pipeline._queue.maxsize = 100

        task = Task(id="full-test", type=TaskKind.ENCODE)
        pipeline.enqueue(task)
        # Should not raise; logs warning and marks task FAILED

    def test_is_queued_checks_in_memory(self, pipeline: Pipeline) -> None:
        task = Task(id="q-check", type=TaskKind.ENCODE, priority=1, payload={"clip_id": "clip-q"})
        pipeline.enqueue(task)
        assert pipeline.is_queued("clip-q") is True

    def test_is_queued_checks_store(self, pipeline: Pipeline) -> None:
        task = Task(id="q-store", type=TaskKind.ENCODE, payload={"clip_id": "clip-store"}, status=TaskStatus.PENDING)
        pipeline._store.insert_task(task)
        assert pipeline.is_queued("clip-store") is True

    def test_is_queued_false_for_nonexistent(self, pipeline: Pipeline) -> None:
        assert pipeline.is_queued("no-such-clip") is False

class TestPauseResume:
    def test_pause_sets_flag(self, pipeline: Pipeline) -> None:
        pipeline.pause()
        assert pipeline.paused is True
        assert "(paused)" in pipeline.get_status()

    def test_resume_clears_flag(self, pipeline: Pipeline) -> None:
        pipeline.pause()
        pipeline.resume()
        assert pipeline.paused is False

    def test_resume_notifies_waiters(self, pipeline: Pipeline) -> None:
        pipeline.pause()
        with pipeline._pause_lock:
            pipeline.resume()
            # notify_all should have been called
            assert pipeline.paused is False

class TestStatus:
    def test_status_encode(self, pipeline: Pipeline) -> None:
        pipeline._inc_counter("encode")
        assert "Encoding 1" in pipeline.get_status()

    def test_status_upload(self, pipeline: Pipeline) -> None:
        pipeline._inc_counter("upload")
        assert "Uploading 1" in pipeline.get_status()

    def test_status_thumbnail(self, pipeline: Pipeline) -> None:
        pipeline._inc_counter("thumbnail")
        assert "Thumbnails 1" in pipeline.get_status()

    def test_status_multiple(self, pipeline: Pipeline) -> None:
        pipeline._inc_counter("encode")
        pipeline._inc_counter("upload")
        status = pipeline.get_status()
        assert "Encoding 1" in status
        assert "Uploading 1" in status

class TestShutdown:
    def test_shutdown_changes_state(self, pipeline: Pipeline) -> None:
        pipeline.start()
        assert pipeline._state.value == "running"
        pipeline.shutdown()
        assert pipeline._state.value == "stopped"

    def test_shutdown_idempotent(self, pipeline: Pipeline) -> None:
        pipeline.start()
        pipeline.shutdown()
        pipeline.shutdown()  # no-op

    def test_shutdown_from_idle_raises(self, pipeline: Pipeline) -> None:
        with pytest.raises(RuntimeError, match="cannot be shut down"):
            pipeline.shutdown()

class TestProcessEncode:
    def test_encode_missing_clip(self, pipeline: Pipeline) -> None:
        task = Task(id="enc-miss", type=TaskKind.ENCODE, payload={"clip_id": "nonexistent"})
        pipeline._process_encode(task)
        # Should not raise, just logs warning and marks FAILED

    def test_encode_success(self, store: Store, config: Config) -> None:
        clip_id = str(uuid.uuid4())
        clip = Clip(id=clip_id, stem="test_encode", source_path=Path("/tmp/test_encode.mkv"), duration=10.0)
        store.insert_clip(clip)

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0)

        with (
            patch("moment.core.pipeline.ffprobe") as mock_probe,
            patch.object(p._encoder, "encode") as mock_encode,
        ):
            mock_probe.return_value = {
                "format": {"duration": "10.0"},
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "60/1"}],
            }
            mock_encode.return_value = Path("/tmp/encoded.mp4")

            task = Task(id="enc-ok", type=TaskKind.ENCODE, payload={"clip_id": clip_id})
            p.start()
            p._process_encode(task)

        p.shutdown()

    def test_encode_failure(self, store: Store, config: Config) -> None:
        clip_id = str(uuid.uuid4())
        clip = Clip(id=clip_id, stem="test_encode_fail", source_path=Path("/tmp/test_encode_fail.mkv"), duration=10.0)
        store.insert_clip(clip)

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0)

        with (
            patch.object(p._encoder, "encode", side_effect=Exception("Encode failed")),
            patch("moment.core.pipeline.ffprobe"),
        ):
            task = Task(id="enc-fail", type=TaskKind.ENCODE, payload={"clip_id": clip_id})
            p.start()
            p._process_encode(task)

            updated = p._store.get_clip(clip_id)
            assert updated is not None
            assert updated.status == ClipStatus.ERROR

        p.shutdown()

class TestProcessUpload:
    def test_upload_missing_clip(self, pipeline: Pipeline) -> None:
        task = Task(id="up-miss", type=TaskKind.UPLOAD, payload={"clip_id": "nonexistent"})
        pipeline._process_upload(task)

    def test_upload_missing_file(self, store: Store, config: Config) -> None:
        clip = Clip(id="up-nofile", stem="test", source_path=Path("/tmp/up_nofile.mkv"))
        store.insert_clip(clip)

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0)
        task = Task(id="up-nofile-task", type=TaskKind.UPLOAD, payload={"clip_id": "up-nofile", "path": "/tmp/nonexistent.mp4"})
        p.start()
        p._process_upload(task)
        p.shutdown()

class TestProcessThumbnail:
    def test_thumbnail_missing_clip(self, pipeline: Pipeline) -> None:
        task = Task(id="th-miss", type=TaskKind.THUMBNAIL, payload={"clip_id": "nonexistent"})
        pipeline._process_thumbnail(task)

    def test_thumbnail_success(self, store: Store, config: Config) -> None:
        clip = Clip(id="thumb-ok", stem="test_thumb", source_path=Path("/tmp/test_thumb.mkv"))
        store.insert_clip(clip)

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0)

        with patch.object(p._thumbnailer, "generate", return_value=Path("/tmp/thumb.jpg")):
            task = Task(id="thumb-ok-task", type=TaskKind.THUMBNAIL, payload={"clip_id": "thumb-ok"})
            p.start()
            p._process_thumbnail(task)

        p.shutdown()

class TestEnqueueShutdownRace:
    def test_enqueue_after_shutdown_still_saves_to_db(self, pipeline: Pipeline) -> None:
        """Enqueue after shutdown() should still persist to DB (durability)."""

        pipeline.start()
        pipeline.shutdown()

        task = Task(id="post-shutdown", type=TaskKind.ENCODE, payload={"clip_id": "c1"})
        pipeline.enqueue(task)

        # Task should be saved to the store even though pipeline is stopped
        pending = pipeline._store.get_pending_tasks()
        assert any(t.id == "post-shutdown" for t in pending)

    def test_enqueue_during_shutdown_does_not_crash(self, pipeline: Pipeline) -> None:
        """Enqueuing while shutdown is in progress should not crash."""
        pipeline.start()

        # Simulate concurrent enqueue + shutdown
        import threading
        results: list[Exception | None] = [None]

        def _enqueue_while_shutdown() -> None:
            try:
                task = Task(id="race-shutdown", type=TaskKind.ENCODE, payload={"clip_id": "c1"})
                pipeline.enqueue(task)
            except Exception as e:
                results[0] = e

        t = threading.Thread(target=_enqueue_while_shutdown)
        t.start()
        pipeline.shutdown()
        t.join()

        assert results[0] is None

@pytest.mark.slow
class TestWrongTaskTypeRequeue:
    def test_encode_worker_requeues_upload_task(self, store: Store, config: Config) -> None:
        """If encode worker picks up a non-ENCODE task, it re-queues it."""
        p = Pipeline(store=store, config=config, encode_workers=1, upload_workers=0, thumbnail_workers=0, on_status=lambda s: None)
        p.start()

        upload_task = Task(id="wrong-type", type=TaskKind.UPLOAD, priority=5, payload={"clip_id": "c1"})
        p.enqueue(upload_task)

        # Worker polls with 1s timeout; wait for it to detect wrong type and re-queue
        wait_until(lambda: any(t.id == "wrong-type" for t in store.get_pending_tasks()),
                   timeout=3.0)

        # The upload task should have been re-queued
        p.shutdown()
        pending = store.get_pending_tasks()
        assert any(t.id == "wrong-type" for t in pending)

    def test_thumbnail_worker_requeues_encode_task(self, store: Store, config: Config) -> None:
        """If thumbnail worker picks up a non-THUMBNAIL task, it re-queues it."""
        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=1)
        p.start()

        encode_task = Task(id="wrong-type-thumb", type=TaskKind.ENCODE, priority=3, payload={"clip_id": "c1"})
        p.enqueue(encode_task)

        wait_until(lambda: any(t.id == "wrong-type-thumb" for t in store.get_pending_tasks()),
                   timeout=3.0)

        p.shutdown()
        pending = store.get_pending_tasks()
        assert any(t.id == "wrong-type-thumb" for t in pending)

    def test_upload_worker_requeues_encode_task(self, store: Store, config: Config) -> None:
        """If upload worker picks up a non-UPLOAD task, it re-queues it."""
        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=1, thumbnail_workers=0)
        p.start()

        encode_task = Task(id="wrong-type-up", type=TaskKind.ENCODE, priority=3, payload={"clip_id": "c1"})
        p.enqueue(encode_task)

        wait_until(lambda: any(t.id == "wrong-type-up" for t in store.get_pending_tasks()),
                   timeout=3.0)

        p.shutdown()
        pending = store.get_pending_tasks()
        assert any(t.id == "wrong-type-up" for t in pending)

class TestSentinelHandling:
    def test_sentinels_not_persisted_by_shutdown(self, store: Store, config: Config) -> None:
        """Sentinels placed in the queue by shutdown() are never saved to DB.

        shutown() places sentinels directly into the PriorityQueue to unblock
        workers, bypassing enqueue() — the only path that persists to the DB.
        This test verifies no sentinel leaks into the tasks table.
        """
        p = Pipeline(store=store, config=config, encode_workers=1, upload_workers=0, thumbnail_workers=0)
        p.start()

        p.shutdown()

        # Query raw DB (not filtered by status=PENDING) to catch any status
        row = store._read_conn.execute(
            "SELECT count(*) as cnt FROM tasks WHERE id = '__sentinel__'"
        ).fetchone()
        assert row["cnt"] == 0

class TestQueueFull:
    def test_queue_full_marks_task_failed(self, pipeline: Pipeline) -> None:
        """When the queue is full, the task is marked FAILED with appropriate message."""
        pipeline.start()

        # Fill the queue manually
        pipeline._queue = MagicMock()
        pipeline._queue.put_nowait.side_effect = __import__("queue").Full()
        pipeline._queue.maxsize = 100

        task = Task(id="queue-full-test", type=TaskKind.ENCODE, priority=5, payload={"clip_id": "c1"})
        pipeline.enqueue(task)

        # Task should be marked FAILED
        pending = pipeline._store.get_pending_tasks()
        assert not any(t.id == "queue-full-test" for t in pending)

        # Check the task status directly
        row = pipeline._store._read_conn.execute(
            "SELECT status, error_message FROM tasks WHERE id = ?", ("queue-full-test",)
        ).fetchone()
        assert row is not None
        assert row["status"] == "FAILED"
        assert "Queue full" in row["error_message"]

        pipeline.shutdown()

@pytest.mark.slow
class TestStatusTimer:
    def test_status_callback_fires(self, store: Store, config: Config) -> None:
        statuses: list[str] = []

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=statuses.append)
        p.start()
        assert "Idle" in statuses
        p.shutdown()

    def test_status_callback_error_handled(self, store: Store, config: Config) -> None:
        def bad_cb(s: str) -> None:
            raise RuntimeError("status error")

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=bad_cb)
        p.start()
        p.shutdown()

    def test_status_timer_does_not_fire_after_shutdown(self, store: Store, config: Config) -> None:
        """After shutdown, the status timer should not fire."""
        statuses: list[str] = []

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=statuses.append)
        p.start()
        statuses.clear()
        p.shutdown()

        # shutdown() cancels the status timer — no wait needed
        assert len(statuses) == 0

    def test_status_timer_fires_on_state_change(self, store: Store, config: Config) -> None:
        """Status callback fires when active counts change."""
        statuses: list[str] = []

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=statuses.append)
        p.start()
        statuses.clear()

        # Change active state
        p._inc_counter("encode")

        # Wait for the status timer (STATUS_INTERVAL=3s) to fire
        wait_until(lambda: any("Encoding" in s for s in statuses),
                   timeout=STATUS_INTERVAL + 2.0)

        assert any("Encoding" in s for s in statuses)
        p.shutdown()

class TestPriorityOrdering:
    def test_higher_priority_tasks_dequeued_first(self, store: Store, config: Config) -> None:
        """Higher priority tasks should be processed before lower priority ones."""
        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0)
        p.start()

        low = Task(id="prio-low", type=TaskKind.ENCODE, priority=1, payload={"clip_id": "c1"})
        high = Task(id="prio-high", type=TaskKind.ENCODE, priority=10, payload={"clip_id": "c2"})

        # Enqueue low first, then high
        p.enqueue(low)
        p.enqueue(high)

        # Both tasks should still be in the queue (no workers to consume them)
        p.shutdown()
        pending = store.get_pending_tasks()
        assert any(t.id == "prio-low" for t in pending)
        assert any(t.id == "prio-high" for t in pending)

class TestCounterEdgeCases:
    def test_dec_multiple_times_below_zero(self, pipeline: Pipeline) -> None:
        """Multiple _dec_counter calls should not go below zero."""
        for _ in range(10):
            pipeline._dec_counter("encode")
        assert pipeline._active_counts["encode"] == 0

    def test_counters_thread_safe(self, pipeline: Pipeline) -> None:
        """Concurrent inc/dec from multiple threads should not corrupt counts."""
        import threading
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(100):
                    pipeline._inc_counter("encode")
                    pipeline._dec_counter("encode")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert pipeline._active_counts["encode"] == 0

class TestCounters:
    def test_inc_and_dec(self, pipeline: Pipeline) -> None:
        pipeline._inc_counter("encode")
        assert pipeline._active_counts["encode"] == 1
        pipeline._inc_counter("encode")
        assert pipeline._active_counts["encode"] == 2
        pipeline._dec_counter("encode")
        assert pipeline._active_counts["encode"] == 1

    def test_dec_below_zero(self, pipeline: Pipeline) -> None:
        pipeline._dec_counter("upload")
        assert pipeline._active_counts["upload"] == 0

@pytest.mark.slow
class TestStatusTimer:
    def test_status_callback_fires(self, store: Store, config: Config) -> None:
        statuses: list[str] = []

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=statuses.append)
        p.start()
        assert "Idle" in statuses
        p.shutdown()

    def test_status_callback_error_handled(self, store: Store, config: Config) -> None:
        def bad_cb(s: str) -> None:
            raise RuntimeError("status error")

        p = Pipeline(store=store, config=config, encode_workers=0, upload_workers=0, thumbnail_workers=0, on_status=bad_cb)
        p.start()
        p.shutdown()


