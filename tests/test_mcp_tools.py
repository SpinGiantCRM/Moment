"""Tests for moment.mcp.tools — MCP tool functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from moment.core.models import Clip, ClipStatus, ClipType, GameProfile, Webhook


# We test the module-level functions, so we need to mock _get_store
@pytest.fixture
def mock_store():
    store = MagicMock()
    return store


class TestListClips:
    @patch("moment.mcp.tools._get_store")
    def test_list_clips_no_paths(self, mock_get_store, mock_store):
        """list_clips must not include _path fields."""
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="test-id",
            stem="test_clip",
            source_path="/home/user/Videos/Moment/test.mp4",
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
        # Path fields must NOT be present
        assert "source_path" not in result[0]
        assert "encoded_path" not in result[0]
        assert "thumb_path" not in result[0]

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
    def test_search_clips_no_paths(self, mock_get_store, mock_store):
        """search_clips must not include _path fields."""
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="search-id",
            stem="found",
            source_path="/home/user/Videos/Moment/found.mp4",
            duration=5.0,
            file_size=500000,
            title="Found Clip",
            game="Game",
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.list_clips.return_value = [clip]

        from moment.mcp.tools import search_clips
        result = search_clips("found")
        assert len(result) == 1
        assert result[0]["title"] == "Found Clip"
        # Path fields must NOT be present
        assert "source_path" not in result[0]
        assert "encoded_path" not in result[0]
        assert "thumb_path" not in result[0]


class TestGetClip:
    @patch("moment.mcp.tools._get_store")
    def test_get_clip_found(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        import os
        home = os.path.expanduser("~")
        clip = Clip(
            id="full-id",
            stem="full",
            source_path=f"{home}/Videos/Moment/full.mkv",
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
        # Paths should be redacted by default (home-relative paths → ~)
        assert result["source_path"] == "~/Videos/Moment/full.mkv"

    @patch("moment.mcp.tools._get_store")
    def test_get_clip_show_paths(self, mock_get_store, mock_store):
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="full-id",
            stem="full",
            source_path="/home/user/Videos/Moment/full.mkv",
            encoded_path="/home/user/.local/share/moment/encoded/full.mp4",
            thumb_path="/home/user/.local/share/moment/thumbnails/full.webp",
            duration=30.0,
            file_size=2000000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import get_clip
        result = get_clip("full-id", show_paths=True)
        assert result is not None
        assert result["source_path"] == "/home/user/Videos/Moment/full.mkv"
        assert result["encoded_path"] == "/home/user/.local/share/moment/encoded/full.mp4"
        assert result["thumb_path"] == "/home/user/.local/share/moment/thumbnails/full.webp"

    @patch("moment.mcp.tools._get_store")
    def test_get_clip_redacted_falls_back_to_filename(self, mock_get_store, mock_store):
        """Paths outside HOME should show just the filename."""
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="ext-id",
            stem="ext",
            source_path="/media/external/clip.mkv",
            duration=5.0,
            file_size=500000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
        )
        mock_store.get_clip.return_value = clip

        from moment.mcp.tools import get_clip
        result = get_clip("ext-id")
        assert result is not None
        assert result["source_path"] == "clip.mkv"

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


class TestWebhookRateLimit:
    """Tests for per-webhook rate limiting in test_webhook()."""

    def test_rate_limit_error_on_rapid_calls(self):
        from moment.mcp.tools import test_webhook, _check_webhook_rate_limit
        from moment.mcp.tools import _webhook_rate_limits

        # Clear state
        _webhook_rate_limits.clear()

        # First call should pass
        error = _check_webhook_rate_limit("hash1")
        assert error is None

        # Immediate second call should be rate-limited
        error = _check_webhook_rate_limit("hash1")
        assert error is not None
        assert "wait" in error.lower() or "seconds" in error.lower()

    def test_different_webhooks_independent(self):
        from moment.mcp.tools import _check_webhook_rate_limit
        from moment.mcp.tools import _webhook_rate_limits

        _webhook_rate_limits.clear()

        # Call webhook A
        assert _check_webhook_rate_limit("hash-a") is None
        # Webhook B should not be rate-limited
        assert _check_webhook_rate_limit("hash-b") is None

    @patch("moment.mcp.tools._check_webhook_rate_limit")
    @patch("moment.mcp.tools._get_store")
    def test_webhook_rate_limit_error_propagated(self, mock_get_store, mock_rate_check, mock_store):
        mock_get_store.return_value = mock_store
        mock_rate_check.return_value = "Please wait 58 seconds before testing this webhook again"

        from moment.core.models import Webhook
        mock_store.list_webhooks.return_value = [
            Webhook(id="wh1", name="test", url="https://discord.com/api/webhooks/123/abc", enabled=True)
        ]

        from moment.mcp.tools import test_webhook
        result = test_webhook("wh1")
        assert "error" in result
        assert "wait" in result["error"]

    @patch.dict("os.environ", {"MOMENT_BYPASS_WEBHOOK_RATE_LIMIT": "1"})
    def test_bypass_env_var(self):
        from moment.mcp.tools import _check_webhook_rate_limit
        from moment.mcp.tools import _webhook_rate_limits

        _webhook_rate_limits.clear()

        # First call sets the timestamp
        _check_webhook_rate_limit("hash-by")
        # Second call should be bypassed due to env var
        error = _check_webhook_rate_limit("hash-by")
        assert error is None


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


# ---------------------------------------------------------------------------
# Visibility enforcement in MCP (Spec 24)
# ---------------------------------------------------------------------------


class TestMCPVisibility:
    @patch("moment.mcp.tools._get_store")
    def test_list_clips_excludes_private_for_guest(self, mock_get_store, mock_store):
        """Guest list_clips (no owner_id) excludes PRIVATE clips."""
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips()
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["owner_id"] is None
        assert call_kwargs["visibility"] is None

    @patch("moment.mcp.tools._get_store")
    def test_list_clips_owner_sees_private(self, mock_get_store, mock_store):
        """Owner list_clips passes owner_id through."""
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips(owner_id="user123")
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["owner_id"] == "user123"

    @patch("moment.mcp.tools._get_store")
    def test_list_clips_visibility_filter(self, mock_get_store, mock_store):
        """Explicit visibility filter is passed through."""
        from moment.core.models import ClipVisibility
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import list_clips
        list_clips(visibility="public")
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["visibility"] == ClipVisibility.PUBLIC

    @patch("moment.mcp.tools._get_store")
    def test_search_clips_owner_passthrough(self, mock_get_store, mock_store):
        """search_clips passes owner_id through for visibility."""
        mock_get_store.return_value = mock_store
        mock_store.list_clips.return_value = []

        from moment.mcp.tools import search_clips
        search_clips("test", owner_id="user456")
        call_kwargs = mock_store.list_clips.call_args.kwargs
        assert call_kwargs["owner_id"] == "user456"

    @patch("moment.mcp.tools._get_store")
    def test_list_clips_response_includes_visibility(self, mock_get_store, mock_store):
        """list_clips response includes visibility field."""
        from moment.core.models import ClipVisibility
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="vis-clip",
            stem="vis",
            source_path="/tmp/vis.mp4",
            duration=10.0,
            file_size=1000000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
            visibility=ClipVisibility.PUBLIC,
        )
        mock_store.list_clips.return_value = [clip]

        from moment.mcp.tools import list_clips
        result = list_clips()
        assert len(result) == 1
        assert result[0]["visibility"] == "public"

    @patch("moment.mcp.tools._get_store")
    def test_search_clips_response_includes_visibility(self, mock_get_store, mock_store):
        """search_clips response includes visibility field."""
        from moment.core.models import ClipVisibility
        mock_get_store.return_value = mock_store
        clip = Clip(
            id="srch-vis",
            stem="sv",
            source_path="/tmp/sv.mp4",
            duration=5.0,
            file_size=500000,
            status=ClipStatus.DONE,
            clip_type=ClipType.VIDEO,
            visibility=ClipVisibility.UNLISTED,
        )
        mock_store.list_clips.return_value = [clip]

        from moment.mcp.tools import search_clips
        result = search_clips("sv")
        assert len(result) == 1
        assert result[0]["visibility"] == "unlisted"
