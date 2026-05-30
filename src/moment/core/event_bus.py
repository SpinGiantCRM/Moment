"""Event bus — centralized QObject-based signal bus for inter-component communication.

All core components emit on the bus instead of accepting raw callbacks.
UI layer connects bus signals to Qt slots for thread-safe delivery.

Signals are grouped into three categories:

    Pipeline
        clip_imported, encode_started, encode_completed, encode_failed,
        upload_started, upload_completed, upload_failed, thumbnail_ready

    System
        gsr_started, gsr_stopped, gsr_crashed,
        game_started, game_stopped

    UI
        window_toggled, toast_requested
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EventBus(QObject):
    """Centralised signal bus that decouples core logic from the UI layer.

    Components emit events here instead of accepting raw callbacks.
    The UI layer connects slots to these signals for thread-safe delivery.

    Usage::

        bus = EventBus()
        bus.encode_completed.connect(some_slot)
        # In a core component:
        bus.encode_completed.emit(clip_id)
    """

    # -- Pipeline events ----------------------------------------------------

    clip_imported = pyqtSignal(object)  # Clip
    encode_started = pyqtSignal(str)  # clip_id
    encode_completed = pyqtSignal(str)  # clip_id
    encode_failed = pyqtSignal(str, str)  # clip_id, error
    upload_started = pyqtSignal(str)  # clip_id
    upload_completed = pyqtSignal(str)  # clip_id
    upload_failed = pyqtSignal(str, str)  # clip_id, error
    thumbnail_ready = pyqtSignal(str)  # clip_id
    thumbnail_progress = pyqtSignal(int, int, str)  # current, total, clip_id

    # -- System events ------------------------------------------------------

    gsr_started = pyqtSignal()
    gsr_stopped = pyqtSignal()
    gsr_crashed = pyqtSignal(str)  # error message
    game_started = pyqtSignal(str)  # game_name
    game_stopped = pyqtSignal(str)  # game_name

    # -- UI events ----------------------------------------------------------

    window_toggled = pyqtSignal(bool)  # visible
    toast_requested = pyqtSignal(str, str)  # message, type
