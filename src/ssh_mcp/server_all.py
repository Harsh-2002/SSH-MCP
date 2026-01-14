"""Streamable HTTP MCP server.

Exposes MCP via Streamable HTTP transport at /mcp.
Streamable HTTP is the current MCP standard (SSE was deprecated as of MCP 2024-11-05).
"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette

from .mcp_server import mcp, lifespan as session_store_lifespan


_streamable_app = mcp.streamable_http_app()


@asynccontextmanager
async def combined_lifespan(app):
    """Initialize SessionStore and Streamable HTTP session manager."""
    async with session_store_lifespan(app):
        async with _streamable_app.router.lifespan_context(app):
            yield


app = Starlette(routes=_streamable_app.routes, lifespan=combined_lifespan)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

