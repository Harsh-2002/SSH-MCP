from mcp.server.fastmcp import FastMCP, Context
from .ssh_manager import SSHManager
from .tools import files, system, monitoring, docker, network
import uvicorn
import os
import logging
from typing import Any

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ssh-mcp-server")

# Initialize FastMCP
mcp = FastMCP("ssh-mcp")

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
    password: str | None = None,
    alias: str = "primary",
    via: str | None = None,
) -> str:
    """
    Connect to a remote server. Creates a persistent session.
    Args:
        alias: Unique name for this connection (e.g. 'web1', 'db1').
    """
    # Cleanup old session if it exists? No, we support multi-connection now.
    # We need to initialize the manager if it doesn't exist.
    manager = getattr(ctx.session, "ssh_manager", None)
    if not manager:
        manager = SSHManager()
        ctx.session.ssh_manager = manager

    try:
        result = await manager.connect(host, username, port, private_key_path, password, alias, via)
        return result
    except Exception as e:
        return f"Error connecting: {str(e)}"

@mcp.tool()
async def disconnect(ctx: Context, alias: str = None) -> str:
    """Disconnect session."""
    manager = get_session_manager(ctx)
    if manager:
        return await manager.disconnect(alias)
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

@mcp.tool()
async def sync(ctx: Context, source_node: str, source_path: str, dest_node: str, dest_path: str) -> str:
    """Stream file from source_node to dest_node efficiently."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await manager.sync(source_node, source_path, dest_node, dest_path)
    except Exception as e:
        return f"Error syncing: {str(e)}"

# --- File Tools ---

@mcp.tool()
async def read(ctx: Context, path: str, target: str = "primary") -> str:
    """Read a remote file."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.read_file(manager, path, target)

@mcp.tool()
async def write(ctx: Context, path: str, content: str, target: str = "primary") -> str:
    """Write content to a remote file (overwrite)."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.write_file(manager, path, content, target)

@mcp.tool()
async def edit(ctx: Context, path: str, old_text: str, new_text: str, target: str = "primary") -> str:
    """Smart replace text in a file. Errors if match is not unique."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.edit_file(manager, path, old_text, new_text, target)

@mcp.tool()
async def list(ctx: Context, path: str, target: str = "primary") -> str:
    """List files in a directory (JSON format)."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.list_directory(manager, path, target)

# --- System Tools ---

@mcp.tool()
async def run(ctx: Context, command: str, target: str = "primary") -> str:
    """Execute a shell command."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.run_command(manager, command, target)

@mcp.tool()
async def info(ctx: Context, target: str = "primary") -> str:
    """Get OS/Kernel details."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.get_system_info(manager, target)

# --- Monitoring Tools ---

@mcp.tool()
async def usage(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Get system resource usage (CPU, RAM, Disk)."""
    manager = get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target}
    try:
        return await monitoring.usage(manager, target)
    except Exception as e:
        return {"error": str(e), "target": target}

@mcp.tool()
async def logs(ctx: Context, path: str, lines: int = 50, grep: str = None, target: str = "primary") -> str:
    """Read recent logs from a file (safer than 'read')."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await monitoring.logs(manager, path, lines, grep, target)
    except Exception as e:
        return f"Error reading logs: {str(e)}"

@mcp.tool()
async def ps(ctx: Context, sort_by: str = "cpu", limit: int = 10, target: str = "primary") -> str:
    """List top processes consuming resources."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await monitoring.ps(manager, sort_by, limit, target)
    except Exception as e:
        return f"Error listing processes: {str(e)}"

# --- Docker Tools ---

@mcp.tool()
async def docker_ps(ctx: Context, all: bool = False, target: str = "primary") -> dict[str, Any]:
    """List Docker containers."""
    manager = get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "all": all}
    try:
        return await docker.docker_ps(manager, all, target)
    except Exception as e:
        return {"error": str(e), "target": target, "all": all}

@mcp.tool()
async def docker_logs(ctx: Context, container_id: str, lines: int = 50, target: str = "primary") -> str:
    """Get logs for a specific container."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await docker.docker_logs(manager, container_id, lines, target)
    except Exception as e:
        return f"Error getting docker logs: {str(e)}"

@mcp.tool()
async def docker_op(ctx: Context, container_id: str, action: str, target: str = "primary") -> str:
    """Perform action (start/stop/restart) on a container."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await docker.docker_op(manager, container_id, action, target)
    except Exception as e:
        return f"Error performing docker action: {str(e)}"

# --- Network Tools ---

@mcp.tool()
async def net_stat(ctx: Context, port: int | None = None, target: str = "primary") -> dict[str, Any]:
    """Check for listening ports (uses ss or netstat)."""
    manager = get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "port": port}
    try:
        return await network.net_stat(manager, port, target)
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

@mcp.tool()
async def net_dump(ctx: Context, interface: str = "any", count: int = 20, filter: str = "", target: str = "primary") -> str:
    """Capture network traffic (tcpdump)."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await network.net_dump(manager, interface, count, filter, target)
    except Exception as e:
        return f"Error capturing traffic: {str(e)}"

@mcp.tool()
async def curl(ctx: Context, url: str, method: str = "GET", target: str = "primary") -> str:
    """Check URL connectivity."""
    manager = get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await network.curl(manager, url, method, target)
    except Exception as e:
        return f"Error running curl: {str(e)}"

# --- App Entry Point ---

app = mcp.sse_app()

def main():
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting SSH MCP Server on http://{host}:{port}")
    mcp.run(transport="sse")

if __name__ == "__main__":
    main()
