"""Tests for moment.mcp.tools — MCP tool functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from moment.core.models import Clip, ClipStatus, ClipType, GameProfile


# We test the module-level functions, so we need to mock _get_store
@pytest.fixture
def mock_store():
    store = MagicMock()
    return store


class TestListClips:
    @patch("moment.mcp.tools._get_store")
    def test_returns_clip_list(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="test-id",
            stem="test_clip",
            source_path="/tmp/test.mp4",
            duration=10.0,
            file_size=1024000,
            title="Test Clip",
            game="Test Game",
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.list_clips.return_value = [clip]

        from moment.mcp.tools import list_clips
        result = list_clips()
        assert len(result) == 1
        assert result[0]["id"] == "test-id"
        assert result[0]["stem"] == "test_clip"
        assert result[0]["status"] == "DONE"

    @patch("moment.mcp.tools._get_store")
    def test_with_status_filter(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips(status="UPLOADED")
        mock_store.list_clips.assert_called_once()
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["status"] == ClipStatus.UPLOADED

    @patch("moment.mcp.tools._get_store")
    def test_with_invalid_status_ignored(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips(status="NONEXISTENT")
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["status"] is None

    @patch("moment.mcp.tools._get_store")
    def test_with_game_filter(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips(game="Elden Ring", limit=10, offset=0)
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["game"] == "Elden Ring"
        assert call_kwargs["limit"] == 10
        assert call_kwargs["offset"] == 0


class TestSearchClips:
    @patch("moment.mcp.tools._get_store")
    def test_search_clips(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="search-id",
            stem="found",
            source_path="/tmp/found.mp4",
            duration=5.0,
            file_size=500000,
            title="Found Clip",
            game="Game",
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.list_clips.return_value = [clip]

        from moment.mcp.tools import search_clips
        result = search_clips("found", game="Game", tag="cool", limit=5)
        assert len(result) == 1
        assert result[0]["title"] == "Found Clip"
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["search"] == "found"
        assert call_kwargs["game"] == "Game"
        assert call_kwargs["tag"] == "cool"


class TestGetClip:
    @patch("moment.mcp.tools._get_store")
    def test_get_clip_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="full-id",
            stem="full",
            source_path="/tmp/full.mp4",
            duration=30.0,
            file_size=2000000,
            title="Full Clip",
            game="Game",
            status=ClipStatus.DONE,
            clip_type=ClipType.IMPORTED,
            video_codec="h264",
            fps=60.0,
            resolution=(1920, 1080),
            has_mic_audio=True,
            has_game_audio=True,
            favorite=True,
            tags=["cool", "highlight"],
            folder="clips",
            watch_count=5,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import get_clip
        result = get_clip("full-id")
        assert result is not None
        assert result["id"] == "full-id"
        assert result["video_codec"] == "h264"
        assert result["fps"] == 60.0
        assert result["resolution"] == [1920, 1080]
        assert result["has_mic_audio"] is True
        assert result["tags"] == ["cool", "highlight"]
        assert result["watch_count"] == 5

    @patch("moment.mcp.tools._get_store")
    def test_get_clip_not_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.get_clip.return_value = None

        from moment.mcp.tools import get_clip
        result = get_clip("missing-id")
        assert result is None


class TestGetStats:
    @patch("moment.mcp.tools._get_store")
    def test_get_stats(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.get_aggregate_stats.return_value = {"total_clips": 42}

        from moment.mcp.tools import get_stats
        result = get_stats()
        assert result == {"total_clips": 42}


class TestListGameProfiles:
    @patch("moment.mcp.tools._get_store")
    def test_list_game_profiles(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        profile = GameProfile(
            id="profile-id",
            game_name="Elden Ring",
            display_name="Elden Ring",
            replay_duration=60,
            capture_fps=60,
            pause_encode=True,
            auto_tag=True,
        )
        mock_store.list_game_profiles.return_value = [profile]

        from moment.mcp.tools import list_game_profiles
        result = list_game_profiles()
        assert len(result) == 1
        assert result[0]["game_name"] == "Elden Ring"
        assert result[0]["capture_fps"] == 60


class TestEnqueueEncode:
    @patch("moment.mcp.tools._get_store")
    def test_enqueue_encode_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="enc-id",
            stem="encode_me",
            source_path="/tmp/enc.mp4",
            duration=10.0,
            file_size=1000000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import enqueue_encode
        result = enqueue_encode("enc-id")
        assert result["status"] == "queued"
        assert result["clip_id"] == "enc-id"

    @patch("moment.mcp.tools._get_store")
    def test_enqueue_encode_not_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.get_clip.return_value = None

        from moment.mcp.tools import enqueue_encode
        result = enqueue_encode("missing")
        assert "error" in result


class TestEnqueueUpload:
    @patch("moment.mcp.tools._get_store")
    def test_enqueue_upload_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="up-id",
            stem="upload_me",
            source_path="/tmp/up.mp4",
            encoded_path="/tmp/up_enc.mp4",
            duration=10.0,
            file_size=1000000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import enqueue_upload
        result = enqueue_upload("up-id")
        assert result["status"] == "queued"

    @patch("moment.mcp.tools._get_store")
    def test_enqueue_upload_no_encoded_path(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="up-id",
            stem="no_enc",
            source_path="/tmp/noenc.mp4",
            encoded_path=None,
            duration=10.0,
            file_size=1000000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import enqueue_upload
        result = enqueue_upload("up-id")
        assert "error" in result
        assert "encoded" in result["error"].lower()

    @patch("moment.mcp.tools._get_store")
    def test_enqueue_upload_not_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        mock_store.get_clip.return_value = None

        from moment.mcp.tools import enqueue_upload
        result = enqueue_upload("missing")
        assert "error" in result


class TestSaveGameProfile:
    @patch("moment.mcp.tools._get_store")
    def test_save_new_profile(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store

        from moment.mcp.tools import save_game_profile
        result = save_game_profile(json.dumps({
            "game_name": "Elden Ring",
            "replay_duration": 60,
            "capture_fps": 120,
        }))
        assert result["status"] == "saved"
        assert result["game_name"] == "Elden Ring"
        mock_store.save_game_profile.assert_called_once()

    @patch("moment.mcp.tools._get_store")
    def test_save_profile_invalid_json(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store

        from moment.mcp.tools import save_game_profile
        result = save_game_profile("not json")
        assert "error" in result

    @patch("moment.mcp.tools._get_store")
    def test_save_profile_missing_game_name(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store

        from moment.mcp.tools import save_game_profile
        result = save_game_profile(json.dumps({"replay_duration": 30}))
        assert "error" in result
        assert "game_name" in result["error"]


class TestRegisterTools:
    def test_register_read_tools(self):
        mock_server = MagicMock()
        from moment.mcp.tools import register_all_tools
        register_all_tools(mock_server, allow_mutations=False)
        # Check that tool() was called (read tools)
        assert mock_server.tool.call_count == 6

    def test_register_with_mutations(self):
        mock_server = MagicMock()
        from moment.mcp.tools import register_all_tools
        register_all_tools(mock_server, allow_mutations=True)
        # 6 read + 4 mutation = 10
        assert mock_server.tool.call_count == 10
