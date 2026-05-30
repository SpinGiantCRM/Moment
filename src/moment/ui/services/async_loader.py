"""AsyncDataLoader — runs blocking calls off the Qt main thread.

Signals ``data_ready`` and ``error_occurred`` are emitted on the main
thread (Qt auto-queues cross-thread signals).  Call ``cancel()`` before
requesting a new load to prevent stale data from appearing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class AsyncDataLoader(QThread):
    """Run *target_fn* in a background thread, emit result/error when done.

    Usage::

        self._loader = AsyncDataLoader(store.list_clips, include_deleted=False)
        self._loader.data_ready.connect(self._on_data_ready)
        self._loader.error_occurred.connect(self._on_error)
        self._loader.start()

    Cancel in-flight loads by calling ``cancel()`` followed by
    ``quit()`` / ``wait()`` — or simply ``cancel()`` and overwrite the
    reference (the thread will finish its DB call but the result will
    be discarded).
    """

    data_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        target_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._target = target_fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False

    def run(self) -> None:
        """Execute the target function and emit the result (unless cancelled)."""
        try:
            result = self._target(*self._args, **self._kwargs)
        except Exception as exc:
            if not self._cancelled:
                logger.exception("AsyncDataLoader error in %s", self._target.__name__)
                self.error_occurred.emit(str(exc))
            return

        if not self._cancelled:
            self.data_ready.emit(result)

    def cancel(self) -> None:
        """Mark this loader as cancelled.

        The underlying DB call may still complete in the background,
        but its result will be discarded.  For a clean shutdown call
        ``quit()`` / ``wait()`` after cancel.
        """
        self._cancelled = True
