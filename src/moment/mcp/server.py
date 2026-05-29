"""fastmcp server setup — optional dependency guarded.

Creates a :class:`fastmcp.FastMCP` server instance and registers all
tools from :mod:`moment.mcp.tools`.  Serves as the glue between
the CLI entry point and the tool definitions.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    from fastmcp import FastMCP

    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False
    FastMCP = None  # type: ignore[assignment]
    logger.info("fastmcp not installed — MCP server features disabled")


def check_available() -> bool:
    """Return ``True`` if fastmcp is installed, ``False`` otherwise."""
    return _FASTMCP_AVAILABLE


def create_server(allow_mutations: bool = False) -> "FastMCP":
    """Create and return a fully-configured FastMCP server instance.

    Args:
        allow_mutations: If ``True``, register pipeline/capture write tools
            in addition to read-only query tools.

    Returns:
        A FastMCP server with all tools registered.

    Raises:
        ImportError: If ``fastmcp`` is not installed.
    """
    if not _FASTMCP_AVAILABLE:
        print(
            "fastmcp not installed.  Run:\n"
            "    pip install moment[mcp]\n"
            "or  pip install fastmcp",
            file=sys.stderr,
        )
        raise ImportError("fastmcp is required for MCP server")

    from moment.mcp.tools import register_all_tools

    server = FastMCP(name="moment", description="Clip management pipeline MCP server")
    register_all_tools(server, allow_mutations=allow_mutations)
    return server
