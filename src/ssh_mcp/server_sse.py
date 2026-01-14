from mcp.server.fastmcp import FastMCP, Context
from .ssh_manager import SSHManager
from .tools import files, system
import uvicorn
import os
import logging

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ssh-mcp-server")

# Initialize FastMCP
mcp = FastMCP("ssh-mcp-saas")

# --- Session Management ---

def get_session_manager(ctx: Context) -> SSHManager:
    """Helper to get or create a session-specific manager."""
    # Note: In a real app, we might want to check auth here
    manager = getattr(ctx.session, "ssh_manager", None)
    if not manager:
        # We don't auto-create here because 'connect' does that.
        # But for type safety we return None or raise
        pass
    return manager

# --- Core Tools ---

@mcp.tool()
async def connect(
    ctx: Context,
    host: str, 
    username: str, 
    port: int = 22, 
    private_key_path: str | None = None, 
    password: str | None = None
) -> str:
    """Connect to a remote server. Creates a persistent session."""
    # Cleanup old session
    if hasattr(ctx.session, "ssh_manager"):
        old: SSHManager = ctx.session.ssh_manager
        await old.disconnect()

    manager = SSHManager()
    try:
        result = await manager.connect(host, username, port, private_key_path, password)
        ctx.session.ssh_manager = manager
        return result
    except Exception as e:
        return f"Error connecting: {str(e)}"

@mcp.tool()
async def disconnect(ctx: Context) -> str:
    """Disconnect session."""
    manager = get_session_manager(ctx)
    if manager:
        await manager.disconnect()
        del ctx.session.ssh_manager
        return "Disconnected."
    return "No active connection."

@mcp.tool()
async def identity(ctx: Context) -> str:
    """
    Get the system's public SSH key to add to authorized_keys on remote targets.
    Returns the key in a markdown code block for easy copying.
    """
    # Create a temporary manager just to get the system key
    temp_manager = SSHManager()
    key = temp_manager.get_public_key()
    return f"```\n{key}\n```"

# --- File Tools ---

@mcp.tool()
async def read(ctx: Context, path: str) -> str:
    """Read a remote file."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.read_file(manager, path)

@mcp.tool()
async def write(ctx: Context, path: str, content: str) -> str:
    """Write content to a remote file (overwrite)."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.write_file(manager, path, content)

@mcp.tool()
async def edit(ctx: Context, path: str, old_text: str, new_text: str) -> str:
    """Smart replace text in a file. Errors if match is not unique."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.edit_file(manager, path, old_text, new_text)

@mcp.tool()
async def list(ctx: Context, path: str) -> str:
    """List files in a directory (JSON format)."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.list_directory(manager, path)

# --- System Tools ---

@mcp.tool()
async def run(ctx: Context, command: str) -> str:
    """Execute a shell command."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.run_command(manager, command)

@mcp.tool()
async def info(ctx: Context) -> str:
    """Get OS/Kernel details."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.get_system_info(manager)

# --- App Entry Point ---

app = mcp.sse_app()

def main():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting SSH MCP SaaS Server on http://{host}:{port}")
    mcp.run(transport="sse")

if __name__ == "__main__":
    main()
