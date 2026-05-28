"""Pipeline — task queue, worker threads, game-aware pausing.

Orchestrates the core data flow:

    Watcher → Store.insert(clip)
      ↓
    Pipeline.enqueue(Task(ENCODE, clip))
      ├─ ffprobe metadata
      ├─ Generate thumbnail (parallel, low priority)
      ├─ Apply EditProfile → ffmpeg NVENC → encoded.mp4
      ├─ rclone copy → R2
      └─ Store.update(status=UPLOADED, r2_url=…)
            ↓
    GUI signals → GridPage updates, Toast appears
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from clip_tray.core.config import Config
from clip_tray.core.encoder import Encoder, EncoderError
from clip_tray.core.game_monitor import GameMonitor
from clip_tray.core.models import (
    Clip,
    ClipStatus,
    EditProfile,
    Task,
    TaskKind,
    TaskStatus,
)
from clip_tray.core.store import Store
from clip_tray.core.thumbnail import Thumbnailer
from clip_tray.core.uploader import Uploader, UploaderError
from clip_tray.utils.ffmpeg import parse_fps, probe as ffprobe

logger = logging.getLogger(__name__)

# Default worker counts
DEFAULT_ENCODE_WORKERS = 1
DEFAULT_UPLOAD_WORKERS = 2
DEFAULT_THUMBNAIL_WORKERS = 1

# Status emit interval (seconds)
STATUS_INTERVAL = 3.0


class Pipeline:
    """Manages the task queue and worker threads that process clips.

    Workers pull tasks from a priority queue and execute them in
    background threads.  Game-aware pausing suspends GPU-heavy tasks
    while a game is active.
    """

    def __init__(
        self,
        store: Store,
        config: Config,
        *,
        encoder: Encoder | None = None,
        uploader: Uploader | None = None,
        thumbnailer: Thumbnailer | None = None,
        game_monitor: GameMonitor | None = None,
        encode_workers: int = DEFAULT_ENCODE_WORKERS,
        upload_workers: int = DEFAULT_UPLOAD_WORKERS,
        thumbnail_workers: int = DEFAULT_THUMBNAIL_WORKERS,
        on_clip_encoded: Callable[[str], None] | None = None,
        on_clip_uploaded: Callable[[str, str], None] | None = None,
        on_clip_errored: Callable[[str, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        """Args:
            store: The application store.
            config: Configuration access.
            encoder: Encoder instance (created if not provided).
            uploader: Uploader instance (created if not provided).
            thumbnailer: Thumbnailer instance (created if not provided).
            game_monitor: GameMonitor instance for game-aware pausing.
            encode_workers: Number of encode worker threads.
            upload_workers: Number of upload worker threads.
            thumbnail_workers: Number of thumbnail worker threads.
            on_clip_encoded: ``callback(stem)`` when encode completes.
            on_clip_uploaded: ``callback(stem, url)`` when upload completes.
            on_clip_errored: ``callback(stem, error_message)`` on failure.
            on_status: ``callback(status_text)`` for processing banner updates.
        """
        self._store = store
        self._config = config

        # Components (injectable for testing)
        self._encoder = encoder or Encoder()
        self._uploader = uploader or Uploader()
        self._thumbnailer = thumbnailer or Thumbnailer()
        self._game_monitor = game_monitor

        # Callbacks
        self._on_clip_encoded = on_clip_encoded
        self._on_clip_uploaded = on_clip_uploaded
        self._on_clip_errored = on_clip_errored
        self._on_status = on_status

        # Task queue — priority ordered (higher = more urgent)
        self._queue: queue.PriorityQueue[tuple[int, Task]] = queue.PriorityQueue()
        self._shutdown = threading.Event()
        self._workers: list[threading.Thread] = []
        self._paused = False
        self._pause_lock = threading.Condition()
        self._active_counts: dict[str, int] = {"encode": 0, "upload": 0, "thumbnail": 0}
        self._counts_lock = threading.Lock()

        # Spawn workers
        for _ in range(encode_workers):
            self._add_worker(self._encode_worker)
        for _ in range(upload_workers):
            self._add_worker(self._upload_worker)
        for _ in range(thumbnail_workers):
            self._add_worker(self._thumbnail_worker)

        # Status reporter timer
        self._status_timer: threading.Timer | None = None
        self._last_status = ""
        self._start_status_timer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, task: Task) -> None:
        """Add a task to the pipeline queue (thread-safe).

        Args:
            task: The task to enqueue.
        """
        # Save to store for durability
        task.status = TaskStatus.PENDING
        self._store.insert_task(task)
        # Push to queue (negate priority because PriorityQueue is min-heap)
        self._queue.put((-task.priority, task))
        logger.debug("Enqueued task %s (type=%s, pri=%d)", task.id, task.type.value, task.priority)

    def shutdown(self) -> None:
        """Signal all workers to exit and wait for them to finish."""
        self._shutdown.set()
        if self._status_timer is not None:
            self._status_timer.cancel()

        # Wake paused workers
        with self._pause_lock:
            self._pause_lock.notify_all()

        # Put sentinel tasks to unblock workers
        for _ in range(len(self._workers)):
            self._queue.put((0, Task(id="__sentinel__", type=TaskKind.ENCODE)))

        for w in self._workers:
            w.join(timeout=30)

        logger.info("Pipeline shutdown complete — %d workers stopped", len(self._workers))

    @property
    def paused(self) -> bool:
        """``True`` when GPU tasks are paused (game active)."""
        return self._paused

    def pause(self) -> None:
        """Pause GPU-intensive tasks (called when game becomes active)."""
        with self._pause_lock:
            self._paused = True
            logger.info("Pipeline paused — GPU tasks suspended")

    def resume(self) -> None:
        """Resume GPU-intensive tasks (called when game exits)."""
        with self._pause_lock:
            self._paused = False
            self._pause_lock.notify_all()
            logger.info("Pipeline resumed — GPU tasks unblocked")

    def get_status(self) -> str:
        """Return a human-readable status string (e.g. ``"Encoding 2/5 …"``)."""
        with self._counts_lock:
            parts: list[str] = []
            if self._active_counts["encode"] > 0:
                parts.append(f"Encoding {self._active_counts['encode']}")
            if self._active_counts["upload"] > 0:
                parts.append(f"Uploading {self._active_counts['upload']}")
            if self._active_counts["thumbnail"] > 0:
                parts.append(f"Thumbnails {self._active_counts['thumbnail']}")
            if self._paused:
                parts.append("(paused)")
            return " • ".join(parts) if parts else "Idle"

    # ------------------------------------------------------------------
    # Worker threads
    # ------------------------------------------------------------------

    def _add_worker(self, target: Callable[[], None]) -> None:
        t = threading.Thread(target=target, daemon=True, name=f"pipeline-{target.__name__}")
        t.start()
        self._workers.append(t)

    def _encode_worker(self) -> None:
        """Worker that processes ENCODE tasks (GPU-bound, serialised by semaphore)."""
        while not self._shutdown.is_set():
            task = self._poll_task(gpu=True)
            if task is None or task.id == "__sentinel__":
                break
            if task.type != TaskKind.ENCODE:
                self._queue.put((-task.priority, task))  # Re-queue
                continue

            self._process_encode(task)

    def _upload_worker(self) -> None:
        """Worker that processes UPLOAD tasks (runs during game)."""
        while not self._shutdown.is_set():
            task = self._poll_task(gpu=False)
            if task is None or task.id == "__sentinel__":
                break
            if task.type != TaskKind.UPLOAD:
                self._queue.put((-task.priority, task))
                continue

            self._process_upload(task)

    def _thumbnail_worker(self) -> None:
        """Worker that processes THUMBNAIL tasks (GPU-bound)."""
        while not self._shutdown.is_set():
            task = self._poll_task(gpu=True)
            if task is None or task.id == "__sentinel__":
                break
            if task.type != TaskKind.THUMBNAIL:
                self._queue.put((-task.priority, task))
                continue

            self._process_thumbnail(task)

    def _poll_task(self, *, gpu: bool) -> Task | None:
        """Get the next task from the queue, respecting game-aware pausing.

        Args:
            gpu: Whether this task uses the GPU (and should pause during games).

        Returns:
            A Task, or ``None`` if the pipeline is shutting down.
        """
        while not self._shutdown.is_set():
            # Respect game pause for GPU tasks
            if gpu:
                with self._pause_lock:
                    while self._paused and not self._shutdown.is_set():
                        self._pause_lock.wait(timeout=1.0)
                    if self._shutdown.is_set():
                        return None

            try:
                _, task = self._queue.get(timeout=1.0)
                return task
            except queue.Empty:
                continue

        return None

    # ------------------------------------------------------------------
    # Task processors
    # ------------------------------------------------------------------

    def _process_encode(self, task: Task) -> None:
        """Execute an encode task."""
        clip_id = task.payload.get("clip_id", "")
        clip = self._store.get_clip(clip_id)
        if clip is None:
            logger.warning("Encode task %s: clip %s not found", task.id, clip_id)
            self._store.update_task_status(task.id, TaskStatus.FAILED, "Clip not found")
            return

        self._store.update_task_status(task.id, TaskStatus.RUNNING)

        try:
            # Probe metadata
            if clip.duration == 0.0:
                probe_data = ffprobe(clip.source_path)
                fmt = probe_data.get("format", {})
                clip.duration = float(fmt.get("duration", 0))
                clip.file_size = clip.source_path.stat().st_size if clip.source_path.is_file() else 0

                video_stream = next(
                    (s for s in probe_data.get("streams", []) if s.get("codec_type") == "video"),
                    None,
                )
                if video_stream:
                    clip.video_codec = video_stream.get("codec_name", "")
                    clip.fps = parse_fps(video_stream.get("r_frame_rate", "0/1"))
                    clip.resolution = (video_stream.get("width", 0), video_stream.get("height", 0))

                audio_streams = [s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"]
                clip.has_game_audio = any(s.get("codec_name") != "opus" for s in audio_streams)
                clip.has_mic_audio = any(s.get("codec_name") == "opus" for s in audio_streams)

            # Get edit profile if it exists
            profile = self._store.get_edit_profile(clip_id)

            # Set status to ENCODING
            clip.status = ClipStatus.ENCODING
            self._store.update_clip(clip)

            # Encode (blocks on GPU semaphore)
            self._inc_counter("encode")
            try:
                output_path = self._encoder.encode(clip, profile)
            finally:
                self._dec_counter("encode")

            # Update clip
            clip.encoded_path = output_path
            clip.status = ClipStatus.DONE
            self._store.update_clip(clip)
            self._store.update_task_status(task.id, TaskStatus.COMPLETED)

            if self._on_clip_encoded is not None:
                self._on_clip_encoded(clip.stem)

            # Auto-enqueue upload
            self.enqueue(Task(
                id=str(uuid.uuid4()),
                type=TaskKind.UPLOAD,
                priority=1,
                payload={"clip_id": clip.id, "path": str(output_path)},
            ))

        except (EncoderError, Exception) as exc:
            logger.error("Encode failed for %s: %s", clip.stem, exc)
            clip.status = ClipStatus.ERROR
            clip.error_message = str(exc)
            self._store.update_clip(clip)
            self._store.update_task_status(task.id, TaskStatus.FAILED, str(exc))

            if self._on_clip_errored is not None:
                self._on_clip_errored(clip.stem, str(exc))

    def _process_upload(self, task: Task) -> None:
        """Execute an upload task."""
        clip_id = task.payload.get("clip_id", "")
        clip = self._store.get_clip(clip_id)
        if clip is None:
            logger.warning("Upload task %s: clip %s not found", task.id, clip_id)
            self._store.update_task_status(task.id, TaskStatus.FAILED, "Clip not found")
            return

        filepath = Path(task.payload.get("path", str(clip.encoded_path or "")))
        if not filepath.is_file():
            self._store.update_task_status(task.id, TaskStatus.FAILED, "File not found")
            return

        self._store.update_task_status(task.id, TaskStatus.RUNNING)

        try:
            clip.status = ClipStatus.UPLOADING
            self._store.update_clip(clip)

            self._inc_counter("upload")
            url = self._uploader.upload(filepath)
            self._dec_counter("upload")

            clip.status = ClipStatus.UPLOADED
            clip.r2_url = url
            clip.uploaded_at = clip.updated_at
            self._store.update_clip(clip)
            self._store.update_task_status(task.id, TaskStatus.COMPLETED)

            if self._on_clip_uploaded is not None:
                self._on_clip_uploaded(clip.stem, url)

        except (UploaderError, Exception) as exc:
            logger.error("Upload failed for %s: %s", clip.stem, exc)
            clip.status = ClipStatus.ERROR
            clip.error_message = str(exc)
            self._store.update_clip(clip)
            self._store.update_task_status(task.id, TaskStatus.FAILED, str(exc))
            self._dec_counter("upload")

            if self._on_clip_errored is not None:
                self._on_clip_errored(clip.stem, str(exc))

    def _process_thumbnail(self, task: Task) -> None:
        """Execute a thumbnail task."""
        clip_id = task.payload.get("clip_id", "")
        clip = self._store.get_clip(clip_id)
        if clip is None:
            logger.warning("Thumbnail task %s: clip %s not found", task.id, clip_id)
            self._store.update_task_status(task.id, TaskStatus.FAILED, "Clip not found")
            return

        self._store.update_task_status(task.id, TaskStatus.RUNNING)

        try:
            self._inc_counter("thumbnail")
            try:
                path = self._thumbnailer.generate(clip)
            finally:
                self._dec_counter("thumbnail")

            if path is not None:
                clip.thumb_path = path
                self._store.update_clip(clip)

            self._store.update_task_status(task.id, TaskStatus.COMPLETED)

        except Exception as exc:
            logger.warning("Thumbnail failed for %s: %s", clip.stem, exc)
            self._store.update_task_status(task.id, TaskStatus.FAILED, str(exc))

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------

    def _start_status_timer(self) -> None:
        """Periodically emit pipeline status to the UI."""
        if self._shutdown.is_set():
            return

        status = self.get_status()
        if status != self._last_status and self._on_status is not None:
            self._last_status = status
            try:
                self._on_status(status)
            except Exception as exc:
                logger.exception("Status callback error: %s", exc)

        self._status_timer = threading.Timer(STATUS_INTERVAL, self._start_status_timer)
        self._status_timer.daemon = True
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Counter helpers
    # ------------------------------------------------------------------

    def _inc_counter(self, name: str) -> None:
        with self._counts_lock:
            self._active_counts[name] = self._active_counts.get(name, 0) + 1

    def _dec_counter(self, name: str) -> None:
        with self._counts_lock:
            self._active_counts[name] = max(0, self._active_counts.get(name, 0) - 1)


