"""Streamable HTTP MCP server.

Exposes MCP via Streamable HTTP transport at /mcp.
Streamable HTTP is the current MCP standard (SSE was deprecated as of MCP 2024-11-05).
"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import RedirectResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from .mcp_server import mcp, lifespan as session_store_lifespan


# Allow connections from any host (universal AI agent compatibility)
_security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)

_session_mgr = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
    stateless=False,
    security_settings=_security_settings,
)


@asynccontextmanager
async def combined_lifespan(app):
    """Initialize SessionStore and Streamable HTTP session manager."""
    async with session_store_lifespan(app):
        async with _session_mgr.run():
            yield


async def redirect_to_mcp_slash(request):
    """Redirect /mcp to /mcp/ to handle trailing slash issue."""
    return RedirectResponse(url="/mcp/", status_code=307)


app = Starlette(
    routes=[
        Route("/mcp", redirect_to_mcp_slash, methods=["GET", "POST", "DELETE"]),
        Mount("/mcp", app=_session_mgr.handle_request),
    ],
    lifespan=combined_lifespan,
)



def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
