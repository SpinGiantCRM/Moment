"""MCP server subcommand — ``moment mcp``.

Exposes Moment as a Model Context Protocol server via ``fastmcp``.
HTTP transport binds to ``127.0.0.1`` only; mutation tools require
a Bearer token (``--api-token``, ``MOMENT_MCP_TOKEN``, or auto-generated).

Usage::

    moment mcp                           # stdio
    moment mcp --http                    # HTTP on 127.0.0.1:8742
    moment mcp --http --port 9000
    moment mcp --allow-mutations         # enable write tools (stdio)
    moment mcp --allow-mutations --api-token "secret123"  # HTTP + auth
"""

from __future__ import annotations

from moment.mcp.main import run_mcp

__all__ = ["run_mcp"]
