"""Combined HTTP server.

Exposes both MCP HTTP transports from a single ASGI app:
- Streamable HTTP at /mcp
- SSE at /sse (with /messages)

This is convenient for custom agent runtimes where some clients only implement
one of the two HTTP transports.
"""

from starlette.applications import Starlette

from .server_sse import mcp, lifespan


_streamable_app = mcp.streamable_http_app()  # includes /mcp
_sse_app = mcp.sse_app()  # includes /sse and /messages mount

# Merge routes into one Starlette app
app = Starlette(routes=[*_streamable_app.routes, *_sse_app.routes], lifespan=lifespan)


def main() -> None:
    # Uses the SDK runner (not required when running via uvicorn)
    # This will start with Streamable HTTP transport.
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
