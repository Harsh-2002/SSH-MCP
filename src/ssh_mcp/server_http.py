from .server_sse import mcp

# Streamable HTTP app (most widely adopted for remote MCP)
app = mcp.streamable_http_app()


def main() -> None:
    # Runs using the SDK's built-in server runner
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
