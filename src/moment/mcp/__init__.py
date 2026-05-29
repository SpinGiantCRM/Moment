"""MCP server subcommand — ``moment mcp``.

Exposes Moment as a Model Context Protocol server via ``fastmcp``.

Usage::

    moment mcp                    # stdio
    moment mcp --http             # HTTP on port 8742
    moment mcp --http --port 9000
    moment mcp --allow-mutations  # enable write tools
"""

from __future__ import annotations

from moment.mcp.main import run_mcp

__all__ = ["run_mcp"]
