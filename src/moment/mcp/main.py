"""CLI entry point for the ``moment mcp`` subcommand.

Parses arguments, creates a FastMCP server, and starts it on the
requested transport (stdio by default, or HTTP).

HTTP transport always binds to ``127.0.0.1`` (localhost only).
Mutation tools (``--allow-mutations``) require a Bearer token via
``--api-token``, ``MOMENT_MCP_TOKEN`` env var, or the ``mcp_api_token``
config key.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from moment.core.config import Config

logger = logging.getLogger(__name__)


def _resolve_api_token(cli_token: str | None) -> str | None:
    """Resolve the MCP API token from available sources.

    Precedence:
        1. CLI ``--api-token`` flag
        2. ``MOMENT_MCP_TOKEN`` environment variable
        3. Config ``mcp_api_token`` setting

    Returns ``None`` if no token is configured anywhere.
    """
    if cli_token:
        return cli_token
    env_token = os.environ.get("MOMENT_MCP_TOKEN", "")
    if env_token:
        return env_token
    config = Config()
    stored = config.get("mcp_api_token")
    return stored if isinstance(stored, str) and stored else None


def run_mcp(argv: list[str] | None = None) -> int:
    """Parse args, create the MCP server, and start it.

    Returns 0 on success, 1 on error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    from moment.mcp.server import check_available, create_server

    if not check_available():
        print(
            "fastmcp not installed.  Run:\n"
            "    pip install moment[mcp]\n"
            "or  pip install fastmcp",
            file=sys.stderr,
        )
        return 1

    api_token = _resolve_api_token(args.api_token)

    try:
        server = create_server(
            allow_mutations=args.allow_mutations,
            api_token=api_token,
        )
    except ImportError:
        return 1

    if args.http:
        port = args.port or 8742
        print(f"MCP server starting on http://127.0.0.1:{port} …")
        server.run(transport="http", host="127.0.0.1", port=port)
    else:
        print("MCP server starting on stdio …", file=sys.stderr)
        server.run(transport="stdio")

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moment mcp",
        description="Start the MCP server for clip management.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP transport instead of stdio.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8742,
        metavar="PORT",
        help="HTTP port (default: 8742, ignored for stdio).",
    )
    parser.add_argument(
        "--allow-mutations",
        action="store_true",
        help="Enable write/pipeline tools (disabled by default).",
    )
    parser.add_argument(
        "--api-token",
        type=str,
        default=None,
        metavar="TOKEN",
        help=(
            "API token for mutation tools. "
            "Also read from MOMENT_MCP_TOKEN env var or config."
        ),
    )
    return parser
