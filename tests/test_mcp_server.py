"""Tests for moment.mcp.server — MCP server creation and auth."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCheckAvailable:
    def test_check_available_when_installed(self):
        with patch("moment.mcp.server._FASTMCP_AVAILABLE", True):
            from moment.mcp.server import check_available
            assert check_available() is True

    def test_check_available_when_not_installed(self):
        with patch("moment.mcp.server._FASTMCP_AVAILABLE", False):
            from moment.mcp.server import check_available
            assert check_available() is False


class TestResolveOrGenerateToken:
    def test_returns_existing_token(self):
        """When a token is passed explicitly, it becomes the mutation token."""
        from moment.mcp.server import _resolve_or_generate_token
        result = _resolve_or_generate_token("existing-token")
        assert result == ("existing-token", None)

    @patch("moment.mcp.server.keyring", None, create=True)
    @patch("moment.mcp.server.secrets")
    def test_generates_token_when_none(self, mock_secrets):
        """When no token exists, generates a new mutation token."""
        mock_secrets.token_urlsafe.return_value = "generated-token-value"
        from moment.mcp.server import _resolve_or_generate_token
        result = _resolve_or_generate_token(None)
        assert result is not None
        assert result[0] == "generated-token-value"
        assert result[1] is None  # No read-only token

    @patch("moment.mcp.server.secrets")
    def test_generated_token_stored_in_keyring(self, mock_secrets):
        """Generated token is persisted to keyring."""
        mock_secrets.token_urlsafe.return_value = "new-keyring-token"
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None  # No existing token
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            from moment.mcp.server import _resolve_or_generate_token
            result = _resolve_or_generate_token(None)
            assert result[0] == "new-keyring-token"
            mock_keyring.set_password.assert_called_once_with(
                "moment", "mcp_api_token", "new-keyring-token"
            )

    @patch("moment.mcp.server.secrets")
    def test_reads_ro_token_from_keyring(self, mock_secrets):
        """Read-only token is read from keyring if available."""
        mock_secrets.token_urlsafe.return_value = "new-mutation"
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = lambda service, key: {
            "mcp_api_token": None,
            "mcp_token_ro": "ro-token-123",
        }.get(key, None)
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            from moment.mcp.server import _resolve_or_generate_token
            result = _resolve_or_generate_token(None)
            assert result == ("new-mutation", "ro-token-123")


class TestCreateServer:
    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    def test_creates_read_only_server(self, mock_fastmcp_class):
        mock_server = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        server = create_server(allow_mutations=False)
        assert server is mock_server
        # Should have been created with name "moment"
        mock_fastmcp_class.assert_called_once()

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_creates_server_with_mutations(self, mock_resolve, mock_fastmcp_class):
        mock_resolve.return_value = ("mut-token", "ro-token")
        mock_server = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        server = create_server(allow_mutations=True)
        assert server is mock_server

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", False)
    def test_raises_when_unavailable(self):
        from moment.mcp.server import create_server
        with pytest.raises(ImportError, match="fastmcp"):
            create_server()

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_creates_with_explicit_token(self, mock_resolve, mock_fastmcp_class):
        mock_resolve.return_value = ("my-token", None)
        mock_server = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=True, api_token="my-token")
        mock_resolve.assert_called_once_with("my-token")


class TestAuthAllRoutes:
    """Verify auth covers ALL routes, not just mutations."""

    def test_auth_no_longer_route_specific(self):
        """_MUTATION_ROUTES is removed — auth middleware now covers all routes."""
        from moment.mcp import server as mcp_server
        assert not hasattr(mcp_server, "_MUTATION_ROUTES"), (
            "_MUTATION_ROUTES should be removed — auth now covers all routes"
        )

    def test_read_only_routes_also_protected(self):
        """Auth middleware no longer excludes read-only routes."""
        from moment.mcp import server as mcp_server
        # The middleware applies to all paths now
        assert not hasattr(mcp_server, "_MUTATION_ROUTES")


class TestAuthMiddleware:
    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_adds_auth_when_app_present(self, mock_resolve, mock_fastmcp_class):
        mock_resolve.return_value = ("secret-token", None)
        mock_server = MagicMock()
        mock_server._app = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=True, api_token="secret-token")
        mock_server._app.middleware.assert_called_once()

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    def test_no_auth_when_no_mutations(self, mock_fastmcp_class):
        mock_server = MagicMock()
        mock_server._app = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=False)
        # Should not try to add middleware
        mock_server._app.middleware.assert_not_called()

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_auth_error_message_says_all_tools(self, mock_resolve, mock_fastmcp_class):
        """The auth error message should say 'All tools' not 'Mutation tools'."""
        mock_resolve.return_value = ("tok", None)
        mock_server = MagicMock()
        mock_server._app = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=True, api_token="tok")
        mock_server._app.middleware.assert_called_once()


class TestScopedTokens:
    """Tests for read-only vs mutation token scoping."""

    def test_mutation_token_names_set(self):
        """_MUTATION_TOOL_NAMES contains all write operations."""
        from moment.mcp.server import _MUTATION_TOOL_NAMES
        assert "enqueue_encode" in _MUTATION_TOOL_NAMES
        assert "enqueue_upload" in _MUTATION_TOOL_NAMES
        assert "save_game_profile" in _MUTATION_TOOL_NAMES
        assert "test_webhook" in _MUTATION_TOOL_NAMES
        assert "list_clips" not in _MUTATION_TOOL_NAMES
        assert "get_stats" not in _MUTATION_TOOL_NAMES

    def test_get_auth_scope_default_none(self):
        """Default auth scope is 'none' before any request."""
        from moment.mcp.server import get_auth_scope
        assert get_auth_scope() == "none"

    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_create_server_passes_ro_token_to_middleware(self, mock_resolve, mock_fastmcp_class):
        """Read-only token is passed to auth middleware when available."""
        mock_resolve.return_value = ("mut", "ro")
        mock_server = MagicMock()
        mock_server._app = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        with patch("moment.mcp.server._add_auth_middleware") as mock_mw:
            create_server(allow_mutations=True)
            mock_mw.assert_called_once_with(mock_server, "mut", "ro")
