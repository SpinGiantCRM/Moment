"""Tests for moment.mcp.main — MCP CLI entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestResolveApiToken:
    def test_cli_token_takes_precedence(self):
        from moment.mcp.main import _resolve_api_token

        result = _resolve_api_token("cli-token")
        assert result == "cli-token"

    @patch.dict("os.environ", {"MOMENT_MCP_TOKEN": "env-token"}, clear=True)
    def test_env_token_fallback(self):
        from moment.mcp.main import _resolve_api_token

        result = _resolve_api_token(None)
        assert result == "env-token"

    @patch.dict("os.environ", {}, clear=True)
    def test_keyring_fallback(self):
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring-token"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            from moment.mcp.main import _resolve_api_token

            result = _resolve_api_token(None)
            assert result == "keyring-token"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_token_returns_none(self):
        with patch.dict("sys.modules", {"keyring": None}):
            from moment.mcp.main import _resolve_api_token

            result = _resolve_api_token(None)
            assert result is None


class TestParser:
    def test_build_parser(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        assert parser.prog == "moment mcp"

    def test_parser_defaults(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args([])
        assert args.http is False
        assert args.port == 8742
        assert args.allow_mutations is False
        assert args.api_token is None

    def test_parser_http_flag(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--http"])
        assert args.http is True

    def test_parser_custom_port(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--http", "--port", "9000"])
        assert args.port == 9000

    def test_parser_allow_mutations(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--allow-mutations"])
        assert args.allow_mutations is True

    def test_parser_api_token(self):
        from moment.mcp.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--api-token", "my-secret"])
        assert args.api_token == "my-secret"


class TestRunMcp:
    @patch("moment.mcp.server.check_available")
    def test_returns_1_when_unavailable(self, mock_check):
        mock_check.return_value = False
        from moment.mcp.main import run_mcp

        result = run_mcp([])
        assert result == 1

    @patch("moment.mcp.server.check_available")
    @patch("moment.mcp.server.create_server")
    @patch("moment.mcp.main._resolve_api_token")
    def test_returns_1_on_import_error(self, mock_resolve, mock_create, mock_check):
        mock_check.return_value = True
        mock_resolve.return_value = None
        mock_create.side_effect = ImportError("fastmcp not found")

        from moment.mcp.main import run_mcp

        result = run_mcp([])
        assert result == 1

    @patch("moment.mcp.server.check_available")
    @patch("moment.mcp.server.create_server")
    @patch("moment.mcp.main._resolve_api_token")
    def test_stdio_transport(self, mock_resolve, mock_create, mock_check):
        mock_check.return_value = True
        mock_resolve.return_value = None
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        from moment.mcp.main import run_mcp

        result = run_mcp([])
        assert result == 0
        mock_server.run.assert_called_once_with(transport="stdio")

    @patch("moment.mcp.server.check_available")
    @patch("moment.mcp.server.create_server")
    @patch("moment.mcp.main._resolve_api_token")
    def test_http_transport_default_port(self, mock_resolve, mock_create, mock_check):
        mock_check.return_value = True
        mock_resolve.return_value = None
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        from moment.mcp.main import run_mcp

        result = run_mcp(["--http"])
        assert result == 0
        mock_server.run.assert_called_once_with(transport="http", host="127.0.0.1", port=8742)

    @patch("moment.mcp.server.check_available")
    @patch("moment.mcp.server.create_server")
    @patch("moment.mcp.main._resolve_api_token")
    def test_http_transport_custom_port(self, mock_resolve, mock_create, mock_check):
        mock_check.return_value = True
        mock_resolve.return_value = None
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        from moment.mcp.main import run_mcp

        result = run_mcp(["--http", "--port", "9999"])
        assert result == 0
        mock_server.run.assert_called_once_with(transport="http", host="127.0.0.1", port=9999)

    @patch("moment.mcp.server.check_available")
    @patch("moment.mcp.server.create_server")
    @patch("moment.mcp.main._resolve_api_token")
    def test_passes_mutations_and_token(self, mock_resolve, mock_create, mock_check):
        mock_check.return_value = True
        mock_resolve.return_value = "token-123"
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        from moment.mcp.main import run_mcp

        run_mcp(["--allow-mutations", "--api-token", "token-123"])
        mock_create.assert_called_once_with(
            allow_mutations=True,
            api_token="token-123",
            http_auth=False,
        )
