"""Tests for moment.ui.editor.gif_exporter — GifExporter."""

from __future__ import annotations
import pytest

from unittest.mock import patch

from moment.ui.editor.gif_exporter import GifExporter
pytestmark = [pytest.mark.gui]


class TestGifExporterInit:
    def test_create_defaults(self, qapp):
        dialog = GifExporter(clip_id="test-id", duration=30.0)
        assert dialog._clip_id == "test-id"
        assert dialog._duration == 30.0
        assert dialog._resolution == "480p"
        assert dialog._fps == 15
        assert dialog._start == 0.0
        assert dialog._end == 30.0
        assert ".gif" in dialog._output_path

    def test_create_zero_duration_clamped(self, qapp):
        dialog = GifExporter(clip_id="test", duration=0.0)
        assert dialog._duration == 0.1

    def test_create_with_source_path(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0, source_path="/tmp/test.mp4")
        assert dialog._source_path == "/tmp/test.mp4"

    def test_signals_exist(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        assert hasattr(dialog, "export_finished")
        assert hasattr(dialog, "export_error")

    def test_output_path_property(self, qapp):
        dialog = GifExporter(clip_id="abc-123", duration=5.0)
        path = dialog.output_path()
        assert "abc-123.gif" in path

    def test_window_title(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        assert dialog.windowTitle() == "Export GIF"

    def test_modal(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        assert dialog.isModal()

class TestGifExporterSettings:
    def test_resolution_change(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._on_resolution("720p")
        assert dialog._resolution == "720p"

    def test_fps_change(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._on_fps("24")
        assert dialog._fps == 24

    def test_fps_change_invalid(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._fps = 15
        dialog._on_fps("not-a-number")
        assert dialog._fps == 15  # unchanged

class TestGifExporterExport:
    def test_export_no_source(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0, source_path="")
        errors = []
        dialog.export_error.connect(lambda msg: errors.append(msg))
        dialog._on_export()
        assert len(errors) == 1
        assert "No source file" in errors[0]

    def test_export_disables_button(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0, source_path="/tmp/test.mp4")
        dialog._export_btn.setEnabled(True)
        dialog._on_export()
        assert not dialog._export_btn.isEnabled()

    def test_export_shows_progress(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0, source_path="/tmp/test.mp4")
        dialog._progress.setVisible(False)
        dialog._on_export()
        assert not dialog._progress.isHidden()

    def test_export_running_flag(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0, source_path="/tmp/test.mp4")
        dialog._on_export()
        assert dialog._running

class TestGifExporterFinish:
    def test_finish_re_enables_ui(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._export_btn.setEnabled(False)
        dialog._progress.setVisible(True)
        dialog._running = True
        dialog._finish()
        assert not dialog._running
        assert dialog._export_btn.isEnabled()
        assert not dialog._progress.isVisible()

    def test_on_export_done_calls_finish(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._running = True
        dialog._export_btn.setEnabled(False)
        dialog._on_export_done("")
        assert not dialog._running
        assert dialog._export_btn.isEnabled()

class TestGifExporterClose:
    def test_close_event_stops_running(self, qapp):
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._running = True
        from PyQt6.QtGui import QCloseEvent
        dialog.closeEvent(QCloseEvent())
        assert not dialog._running

class TestGifExporterBrowse:
    @patch("moment.ui.editor.gif_exporter.QFileDialog.getSaveFileName")
    def test_browse_sets_path(self, mock_dlg, qapp):
        mock_dlg.return_value = ("/home/user/Pictures/test.gif", "GIF (*.gif)")
        dialog = GifExporter(clip_id="test", duration=10.0)
        dialog._on_browse_output()
        assert dialog._output_path == "/home/user/Pictures/test.gif"
        assert dialog._out_input.text() == "/home/user/Pictures/test.gif"

    @patch("moment.ui.editor.gif_exporter.QFileDialog.getSaveFileName")
    def test_browse_cancelled(self, mock_dlg, qapp):
        mock_dlg.return_value = ("", "")
        dialog = GifExporter(clip_id="test", duration=10.0)
        original = dialog._output_path
        dialog._on_browse_output()
        assert dialog._output_path == original  # unchanged


