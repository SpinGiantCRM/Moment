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
        from moment.mcp.server import _resolve_or_generate_token
        result = _resolve_or_generate_token("existing-token")
        assert result == "existing-token"

    @patch("moment.mcp.server.Config")
    def test_generates_token_when_none(self, mock_config_cls):
        from moment.mcp.server import _resolve_or_generate_token
        result = _resolve_or_generate_token(None)
        assert result is not None
        assert len(result) > 0

    @patch("moment.mcp.server.Config")
    def test_generated_token_persisted(self, mock_config_cls):
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        from moment.mcp.server import _resolve_or_generate_token
        result = _resolve_or_generate_token(None)
        mock_config.set.assert_called_once()
        assert mock_config.set.call_args[0][0] == "mcp_api_token"
        assert mock_config.set.call_args[0][1] == result


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
        mock_resolve.return_value = "test-token"
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
        mock_resolve.return_value = "my-token"
        mock_server = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=True, api_token="my-token")
        # _resolve_or_generate_token is called but just returns the existing token
        mock_resolve.assert_called_once_with("my-token")


class TestAuthMiddleware:
    @patch("moment.mcp.server._FASTMCP_AVAILABLE", True)
    @patch("moment.mcp.server.FastMCP")
    @patch("moment.mcp.server._resolve_or_generate_token")
    def test_adds_auth_when_app_present(self, mock_resolve, mock_fastmcp_class):
        mock_resolve.return_value = "secret-token"
        mock_server = MagicMock()
        mock_server._app = MagicMock()
        mock_fastmcp_class.return_value = mock_server

        from moment.mcp.server import create_server
        create_server(allow_mutations=True, api_token="secret-token")
        # Middleware should have been registered
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
