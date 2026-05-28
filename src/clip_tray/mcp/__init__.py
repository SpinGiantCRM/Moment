"""MCP server subcommand — ``clip-tray mcp``.

Exposes clip-tray as a Model Context Protocol server via ``fastmcp``.
Supports both stdio and HTTP transports.

Usage::

    clip-tray mcp                    # stdio
    clip-tray mcp --http             # HTTP on port 8742
    clip-tray mcp --http --port 9000
    clip-tray mcp --allow-mutations  # enable write tools
"""

from __future__ import annotations

from clip_tray.mcp.main import run_mcp

__all__ = ["run_mcp"]
