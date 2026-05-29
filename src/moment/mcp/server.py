"""fastmcp server setup — optional dependency guarded.

Creates a :class:`fastmcp.FastMCP` server instance and registers all
tools from :mod:`moment.mcp.tools`.  Serves as the glue between
the CLI entry point and the tool definitions.

When mutations are enabled and HTTP transport is used, an
Authorization Bearer token is required for all mutation tool calls.
Read-only tools remain unauthenticated.  stdio transport is
unaffected by auth.
"""

from __future__ import annotations

import logging
import secrets
import sys

from moment.core.config import Config

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


# Set of mutation tool names — these require auth
_MUTATION_TOOLS = frozenset({
    "enqueue_encode",
    "enqueue_upload",
    "save_game_profile",
    "test_webhook",
})


def _resolve_or_generate_token(api_token: str | None) -> str | None:
    """Return the API token, auto-generating and persisting one if needed.

    If *api_token* is already set, return it as-is.  Otherwise, generate
    a cryptographically random token, persist it in the Config DB, and
    log it at INFO level (log file only, never stdout).
    """
    if api_token:
        return api_token

    # Auto-generate and persist
    token = secrets.token_urlsafe(32)
    try:
        config = Config()
        config.set("mcp_api_token", token)
    except Exception as exc:
        logger.warning("Could not persist auto-generated MCP token: %s", exc)

    logger.info("Auto-generated MCP API token for mutation tools")
    return token


def create_server(
    allow_mutations: bool = False,
    api_token: str | None = None,
) -> "FastMCP":
    """Create and return a fully-configured FastMCP server instance.

    Args:
        allow_mutations: If ``True``, register pipeline/capture write tools
            in addition to read-only query tools.  Mutation tools will
            require an ``Authorization: Bearer <token>`` header when
            accessed via HTTP.
        api_token: API token for mutation tools.  If ``None`` and
            *allow_mutations* is ``True``, a random token is
            auto-generated and persisted in the Config DB.

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

    server = FastMCP(
        name="moment",
        description="Clip management pipeline MCP server",
    )

    if allow_mutations:
        api_token = _resolve_or_generate_token(api_token)

    register_all_tools(server, allow_mutations=allow_mutations)

    # Attach auth middleware if mutations are enabled with a token
    if allow_mutations and api_token:
        _add_auth_middleware(server, api_token)

    return server


def _add_auth_middleware(server: "FastMCP", token: str) -> None:
    """Add FastAPI middleware that requires a Bearer token for mutation tools.

    Read-only tools pass through without authentication.
    """
    app = server._app if hasattr(server, "_app") else getattr(server, "app", None)
    if app is None:
        logger.warning("Cannot add auth middleware — no FastAPI app found")
        return

    @app.middleware("http")
    async def _mcp_auth_middleware(request, call_next):
        path = request.url.path
        # Check if this request targets a mutation tool
        is_mutation = any(tool in path for tool in _MUTATION_TOOLS)
        if is_mutation:
            auth_header = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if auth_header != expected:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401,
                    content={
                        "error": (
                            "Missing or invalid Authorization header. "
                            "Mutation tools require 'Authorization: Bearer <token>'."
                        ),
                    },
                )
        response = await call_next(request)
        return response

    logger.debug("Auth middleware registered for %d mutation tools", len(_MUTATION_TOOLS))
