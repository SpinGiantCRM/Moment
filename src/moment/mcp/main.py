"""CLI entry point for the ``moment mcp`` subcommand.

Parses arguments, creates a FastMCP server, and starts it on the
requested transport (stdio by default, or HTTP).
"""

from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger(__name__)


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

    try:
        server = create_server(allow_mutations=args.allow_mutations)
    except ImportError:
        return 1

    if args.http:
        port = args.port or 8742
        print(f"MCP server starting on HTTP port {port} …")
        server.run(transport="http", port=port)
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
    return parser
