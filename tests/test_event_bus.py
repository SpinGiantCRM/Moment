"""Tests for core/event_bus.py — signal bus."""

from __future__ import annotations

import pytest

from moment.core.event_bus import EventBus

pytestmark = [pytest.mark.integration]


class TestEventBus:
    def test_signals_exist(self) -> None:
        bus = EventBus()
        assert hasattr(bus, "clip_imported")
        assert hasattr(bus, "encode_started")
        assert hasattr(bus, "encode_completed")
        assert hasattr(bus, "encode_failed")
        assert hasattr(bus, "upload_started")
        assert hasattr(bus, "upload_completed")
        assert hasattr(bus, "upload_failed")
        assert hasattr(bus, "thumbnail_ready")
        assert hasattr(bus, "thumbnail_progress")
        assert hasattr(bus, "gsr_started")
        assert hasattr(bus, "gsr_stopped")
        assert hasattr(bus, "gsr_crashed")
        assert hasattr(bus, "game_started")
        assert hasattr(bus, "game_stopped")
        assert hasattr(bus, "window_toggled")
        assert hasattr(bus, "toast_requested")

    def test_emit_connect_round_trip(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def on_encode_completed(clip_id: str) -> None:
            results.append(clip_id)

        bus.encode_completed.connect(on_encode_completed)
        bus.encode_completed.emit("clip-123")
        assert results == ["clip-123"]

    def test_multiple_handlers(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def handler1(clip_id: str) -> None:
            results.append(f"1:{clip_id}")

        def handler2(clip_id: str) -> None:
            results.append(f"2:{clip_id}")

        bus.encode_completed.connect(handler1)
        bus.encode_completed.connect(handler2)
        bus.encode_completed.emit("test-id")
        assert len(results) == 2

    def test_gsi_crashed_signal(self) -> None:
        bus = EventBus()
        results: list[str] = []

        def on_crash(msg: str) -> None:
            results.append(msg)

        bus.gsr_crashed.connect(on_crash)
        bus.gsr_crashed.emit("OOM error")
        assert results == ["OOM error"]

    def test_game_started_stopped(self) -> None:
        bus = EventBus()
        started: list[str] = []
        stopped: list[str] = []

        bus.game_started.connect(started.append)
        bus.game_stopped.connect(stopped.append)
        bus.game_started.emit("cs2")
        bus.game_stopped.emit("cs2")
        assert started == ["cs2"]
        assert stopped == ["cs2"]

    def test_window_toggled(self) -> None:
        bus = EventBus()
        states: list[bool] = []

        bus.window_toggled.connect(states.append)
        bus.window_toggled.emit(True)
        bus.window_toggled.emit(False)
        assert states == [True, False]

    def test_toast_requested(self) -> None:
        bus = EventBus()
        toasts: list[tuple[str, str]] = []

        def on_toast(msg: str, typ: str) -> None:
            toasts.append((msg, typ))

        bus.toast_requested.connect(on_toast)
        bus.toast_requested.emit("Hello", "info")
        assert toasts == [("Hello", "info")]
