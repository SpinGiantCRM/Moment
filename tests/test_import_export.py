"""Tests for core/import_export.py — clip import + export."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.import_export import (
    CLIPS_DIR,
    ImportError,
    ImportExport,
)
from moment.core.models import Clip, ClipStatus, ClipType
from moment.utils.ffmpeg import parse_fps


@pytest.fixture
def ie(store):
    """Return an ImportExport backed by the test store."""
    return ImportExport(store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestParseFps:
    def test_simple(self):
        assert parse_fps("30") == 30.0

    def test_fractional(self):
        assert parse_fps("30000/1001") == pytest.approx(29.97, abs=0.05)

    def test_invalid(self):
        assert parse_fps("abc") == 0.0
        assert parse_fps("0/0") == 0.0


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImport:
    def test_import_file_missing(self, ie):
        with pytest.raises(ImportError, match="not found"):
            ie.import_file(Path("/tmp/nonexistent_import_test.mp4"))

    def test_import_file_empty(self, ie):
        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="empty_import_")
        os.close(fd)
        # Create a 0-byte file
        Path(tmp).write_text("")
        try:
            with pytest.raises(ImportError, match="empty"):
                ie.import_file(Path(tmp))
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    @patch("moment.core.import_export.ffprobe")
    @patch("moment.core.import_export.Thumbnailer")
    @patch("moment.core.import_export.shutil.copy2")
    @patch("moment.core.import_export.ensure_dir")
    @patch.object(ImportExport, "_check_mime_type", return_value=None)
    def test_import_basic(
        self, mock_mime, mock_ensure, mock_copy, mock_thumb_cls, mock_probe, ie
    ):
        """Happy path: probe returns valid data, thumbnail succeeds, clip inserted."""
        mock_probe.return_value = {
            "format": {"duration": "25.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "60/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        mock_thumb = MagicMock()
        mock_thumb.generate.return_value = Path("/tmp/thumb.jpg")
        mock_thumb_cls.return_value = mock_thumb

        # Make copy2 actually create the destination file so stat() succeeds
        def _fake_copy(src, dst):
            Path(dst).write_bytes(b"x" * 100)
            return dst
        mock_copy.side_effect = _fake_copy

        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="import_test_")
        os.close(fd)
        Path(tmp).write_bytes(b"fake video data" * 100)
        try:
            clip = ie.import_file(Path(tmp), copy=True)
            assert clip is not None
            assert clip.duration == 25.5
            assert clip.fps == 60.0
            assert clip.resolution == (1920, 1080)
            assert clip.video_codec == "h264"
            assert clip.has_game_audio is True
            assert clip.clip_type == ClipType.IMPORTED
            assert clip.status == ClipStatus.DONE
            assert clip.source_app == "import"
            assert clip.original_filename is not None
            # Verify copy was called
            mock_copy.assert_called_once()
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    @patch("moment.core.import_export.ffprobe")
    @patch("moment.core.import_export.Thumbnailer")
    @patch("moment.core.import_export.ensure_dir")
    @patch.object(ImportExport, "_check_mime_type", return_value=None)
    def test_import_no_copy(
        self, mock_mime, mock_ensure, mock_thumb_cls, mock_probe, ie
    ):
        """With copy=False, the source_path stays as the original file."""
        mock_probe.return_value = {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "r_frame_rate": "30/1"},
            ],
        }
        mock_thumb = MagicMock()
        mock_thumb.generate.return_value = None
        mock_thumb_cls.return_value = mock_thumb

        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="import_nocopy_")
        os.close(fd)
        Path(tmp).write_bytes(b"fake data" * 50)
        try:
            clip = ie.import_file(Path(tmp), copy=False)
            assert clip.source_path == Path(tmp)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    @patch("moment.core.import_export.ffprobe")
    @patch("moment.core.import_export.ensure_dir")
    @patch.object(ImportExport, "_check_mime_type", return_value=None)
    def test_import_no_video_stream(
        self, mock_mime, mock_ensure, mock_probe, ie
    ):
        """If no video stream is found, it should raise ImportError."""
        mock_probe.return_value = {
            "format": {"duration": "5.0"},
            "streams": [
                {"codec_type": "audio", "codec_name": "mp3"},
            ],
        }
        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="no_video_")
        os.close(fd)
        Path(tmp).write_bytes(b"data")
        try:
            with pytest.raises(ImportError, match="No video stream"):
                ie.import_file(Path(tmp), copy=False)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    @patch("moment.core.import_export.ffprobe")
    @patch("moment.core.import_export.Thumbnailer")
    @patch("moment.core.import_export.ensure_dir")
    @patch.object(ImportExport, "_check_mime_type", return_value=None)
    def test_import_with_game_and_tags(
        self, mock_mime, mock_ensure, mock_thumb_cls, mock_probe, ie
    ):
        mock_probe.return_value = {
            "format": {"duration": "60.0"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "r_frame_rate": "24/1"},
            ],
        }
        mock_thumb = MagicMock()
        mock_thumb.generate.return_value = None
        mock_thumb_cls.return_value = mock_thumb

        fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="tagged_")
        os.close(fd)
        Path(tmp).write_bytes(b"data")
        try:
            clip = ie.import_file(Path(tmp), copy=False, game="elden-ring", tags=["boss", "no-hit"])
            assert clip.game == "elden-ring"
            assert clip.tags == ["boss", "no-hit"]
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_empty_list(self, ie):
        count = ie.export_clips([], Path("/tmp/export_test"))
        assert count == 0

    def test_export_nonexistent_clip(self, ie):
        count = ie.export_clips(["nonexistent"], Path("/tmp/export_test"))
        assert count == 0

    def test_export_clip_without_encoded_file(self, store, ie):
        """Clip exists but has no encoded_path."""
        clip = Clip(
            id="no-enc", stem="test", source_path=Path("/tmp/test.mkv"),
            encoded_path=None, status=ClipStatus.DONE,
        )
        store.insert_clip(clip)
        count = ie.export_clips(["no-enc"], Path("/tmp/export_test"))
        assert count == 0

    @patch("moment.core.import_export.shutil.copy2")
    def test_export_success(self, mock_copy, store, ie):
        encoded = Path("/tmp/fake-encoded.mp4")
        encoded.touch()
        clip = Clip(
            id="has-enc", stem="test", source_path=Path("/tmp/test.mkv"),
            encoded_path=encoded, status=ClipStatus.DONE,
        )
        store.insert_clip(clip)
        try:
            count = ie.export_clips(["has-enc"], Path("/tmp/export_dest"))
            assert count == 1
            mock_copy.assert_called_once()
        finally:
            try:
                encoded.unlink()
            except FileNotFoundError:
                pass

    def test_export_symlink_outside_allowed_raises(self, store, ie, tmp_path: Path):
        """Spec 22: Export via symlink pointing outside allowed dirs is blocked."""
        # Create a real file in tmp_path (allowed)
        real_file = tmp_path / "safe.mp4"
        real_file.write_bytes(b"x" * 100)

        # Create a symlink inside tmp_path pointing to /etc/shadow (outside)
        symlink = tmp_path / "evil_link.mp4"
        symlink.symlink_to("/etc/shadow")

        clip = Clip(
            id="symlink-clip", stem="symlink",
            source_path=real_file,
            encoded_path=symlink,
            status=ClipStatus.DONE,
        )
        store.insert_clip(clip)

        with pytest.raises(ImportError, match="outside allowed"):
            ie.export_clips(["symlink-clip"], tmp_path / "export_dest")

    def test_export_symlink_within_allowed_succeeds(self, store, ie, tmp_path: Path):
        """Spec 22: Symlink within allowed dirs resolves and exports fine."""
        real_file = tmp_path / "real_clip.mp4"
        real_file.write_bytes(b"x" * 100)

        symlink = tmp_path / "link.mp4"
        symlink.symlink_to(real_file)

        clip = Clip(
            id="symlink-safe", stem="symlink_safe",
            source_path=real_file,
            encoded_path=symlink,
            status=ClipStatus.DONE,
        )
        store.insert_clip(clip)

        dest = tmp_path / "export_out"
        count = ie.export_clips(["symlink-safe"], dest)
        assert count == 1
        assert (dest / "link.mp4").exists()


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


class TestPresets:
    def test_list_presets_returns_all(self, ie):
        presets = ie.list_presets()
        assert "game" in presets
        assert "archive" in presets
        assert "streaming" in presets
        assert presets["game"]["codec"] == "h264"
        assert presets["game"]["quality"] == 23
        assert presets["archive"]["codec"] == "h265"
