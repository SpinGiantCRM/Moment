"""fastmcp server setup — optional dependency guarded.

Creates a :class:`fastmcp.FastMCP` server instance and registers all
tools from :mod:`moment.mcp.tools`.  Serves as the glue between
the CLI entry point and the tool definitions.

**Token tiers:**

* **Mutation token** (``moment_mcp_token`` in keyring) — full access to
  all tools including write operations.
* **Read-only token** (``moment_mcp_token_ro`` in keyring) — only
  read tools (list/search/get clips, stats, game profiles).
  Mutation tool calls return 403.
* **No token** — only read tools are accessible (same as read-only).

When mutations are enabled and HTTP transport is used, an
Authorization Bearer token is required for **all** tool calls.
stdio transport is unaffected by auth.
"""

from __future__ import annotations

import contextvars
import hmac
import logging
import random
import secrets
import sys
import time as time_module

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth context — propagated via contextvars for downstream tool access
# ---------------------------------------------------------------------------

_auth_scope: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_auth_scope", default="none"
)
# Possible values: "none", "read-only", "mutation"

_MUTATION_TOOL_NAMES: set[str] = {
    "enqueue_encode",
    "enqueue_upload",
    "save_game_profile",
    "test_webhook",
}


def get_auth_scope() -> str:
    """Return the current request's auth scope (``none``, ``read-only``, ``mutation``)."""
    return _auth_scope.get()

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



def _resolve_or_generate_token(api_token: str | None) -> tuple[str, str] | None:
    """Return ``(mutation_token, read_only_token)`` or ``None``.

    Resolution order (mutation token):
        1. *api_token* argument (CLI / env).
        2. ``moment/mcp_api_token`` from system keyring.
        3. Generate + store in keyring.

    Read-only token:
        1. ``moment/mcp_token_ro`` from system keyring (optional).
        2. If absent → ``None`` (mutation token serves reads too).

    Tokens are **never** written to the config/settings DB table.
    """
    mutation_token = api_token

    # Resolve mutation token
    if not mutation_token:
        try:
            import keyring
            mutation_token = keyring.get_password("moment", "mcp_api_token")
            if mutation_token:
                logger.info("MCP API token loaded from system keyring")
        except Exception as exc:
            logger.debug("keyring lookup skipped: %s", exc)

    if not mutation_token:
        mutation_token = secrets.token_urlsafe(32)
        keyring_ok = False
        try:
            import keyring
            keyring.set_password("moment", "mcp_api_token", mutation_token)
            keyring_ok = True
            logger.info("MCP API token stored in system keyring")
        except Exception as exc:
            logger.warning(
                "Could not store MCP token in keyring — token will be session-only"
            )
            logger.debug("keyring store error: %s", exc)
        if not keyring_ok:
            logger.warning(
                "SESSION-ONLY MCP TOKEN — will change on next restart. "
                "Set MOMENT_MCP_TOKEN env var or install keyring."
            )

    # Resolve read-only token (optional)
    ro_token = None
    try:
        import keyring
        ro_token = keyring.get_password("moment", "mcp_token_ro")
        if ro_token:
            logger.info("MCP read-only token loaded from system keyring")
    except Exception as exc:
        logger.debug("read-only keyring lookup skipped: %s", exc)

    return (mutation_token, ro_token)


def create_server(
    allow_mutations: bool = False,
    api_token: str | None = None,
) -> "FastMCP":
    """Create and return a fully-configured FastMCP server instance.

    Args:
        allow_mutations: If ``True``, register pipeline/capture write tools
            in addition to read-only query tools.  Mutation tools will
            require a mutation-scoped ``Authorization: Bearer <token>``.
        api_token: API token for mutation tools.  If ``None`` and
            *allow_mutations* is ``True``, a random token is
            auto-generated and persisted in keyring.

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

    tokens = None
    if allow_mutations:
        tokens = _resolve_or_generate_token(api_token)

    register_all_tools(server, allow_mutations=allow_mutations)

    # Attach auth middleware if mutations are enabled with a token
    if allow_mutations and tokens:
        _add_auth_middleware(server, tokens[0], tokens[1])

    return server


def _add_auth_middleware(server: "FastMCP", mutation_token: str, ro_token: str | None = None) -> None:
    """Add FastAPI middleware with scoped Bearer-token authentication.

    Token scoping:
        - ``Authorization: Bearer <mutation_token>`` → full access (mutation scope).
        - ``Authorization: Bearer <ro_token>`` → read-only scope.  Mutation tool
          calls receive 403 Forbidden.
        - Invalid/missing token → 401 Unauthorized.

    Auth failures incur a random 50–200 ms delay to frustrate timing attacks.
    stdio transport is unaffected (middleware only fires on HTTP).
    """

    app = server._app if hasattr(server, "_app") else getattr(server, "app", None)
    if app is None:
        logger.warning("Cannot add auth middleware — no FastAPI app found")
        return

    @app.middleware("http")
    async def _mcp_auth_middleware(request, call_next):
        from fastapi.responses import JSONResponse

        auth_header = request.headers.get("Authorization", "")

        # Determine token scope
        scope = "none"
        expected_mutation = f"Bearer {mutation_token}"
        if hmac.compare_digest(auth_header, expected_mutation):
            scope = "mutation"
        elif ro_token and hmac.compare_digest(auth_header, f"Bearer {ro_token}"):
            scope = "read-only"
        else:
            # Invalid or missing token
            time_module.sleep(random.uniform(0.05, 0.2))
            return JSONResponse(
                status_code=401,
                content={
                    "error": (
                        "Missing or invalid Authorization header. "
                        "All tools require 'Authorization: Bearer <token>'."
                    ),
                },
            )

        # Scope enforcement is handled by each tool via
        # _check_mutation_allowed() — we only set the contextvar here.
        # DO NOT parse the request body (consumes the stream, breaking
        # downstream FastMCP dispatch).
        _auth_scope.set(scope)

        response = await call_next(request)
        return response

    logger.debug("Auth middleware registered — scoped Bearer token required for all HTTP routes")
