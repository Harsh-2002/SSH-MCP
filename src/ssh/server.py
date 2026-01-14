from mcp.server.fastmcp import FastMCP
from .ssh_manager import SSHManager
from .tools import files, system, monitoring, docker, network
import logging
from typing import Any

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ssh-mcp-cli")

# Initialize the CLI Server
mcp = FastMCP("ssh-mcp")

# Global Instance for CLI Mode
ssh = SSHManager()

@mcp.tool()
async def connect(
    host: str, 
    username: str, 
    port: int = 22, 
    private_key_path: str | None = None, 
    password: str | None = None,
    alias: str = "primary",
    via: str | None = None,
) -> str:
    """Connect to a remote server via SSH."""
    try:
        return await ssh.connect(host, username, port, private_key_path, password, alias, via)
    except Exception as e:
        return f"Error connecting: {str(e)}"

@mcp.tool()
async def run(command: str, target: str | None = None) -> str:
    """Execute a shell command."""
    try:
        return await system.run_command(ssh, command, target)
    except Exception as e:
        return f"Error executing command: {str(e)}"

@mcp.tool()
async def info(target: str | None = None) -> str:
    """Get OS/Kernel details."""
    try:
        return await system.get_system_info(ssh, target)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def disconnect(alias: str | None = None) -> str:
    """Disconnect session."""
    try:
        return await ssh.disconnect(alias)
    except Exception as e:
        return f"Error disconnecting: {str(e)}"

@mcp.tool()
async def identity() -> str:
    """Get the system's public SSH key to add to authorized_keys on remote targets."""
    return ssh.get_public_key()

# --- File Tools ---

@mcp.tool()
async def read(path: str, target: str | None = None) -> str:
    """Read a remote file."""
    try:
        return await files.read_file(ssh, path, target)
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
async def write(path: str, content: str, target: str | None = None) -> str:
    """Write content to a remote file."""
    try:
        return await files.write_file(ssh, path, content, target)
    except Exception as e:
        return f"Error writing file: {str(e)}"

@mcp.tool()
async def edit(path: str, old_text: str, new_text: str, target: str | None = None) -> str:
    """Smart replace text in a file."""
    try:
        return await files.edit_file(ssh, path, old_text, new_text, target)
    except Exception as e:
        return f"Error editing file: {str(e)}"

@mcp.tool()
async def list(path: str, target: str | None = None) -> str:
    """List files in a directory."""
    try:
        return await files.list_directory(ssh, path, target)
    except Exception as e:
        return f"Error listing directory: {str(e)}"

@mcp.tool()
async def sync(
    source_node: str,
    source_path: str,
    dest_node: str,
    dest_path: str
) -> str:
    """Stream file from source_node to dest_node efficiently."""
    try:
        return await ssh.sync(source_node, source_path, dest_node, dest_path)
    except Exception as e:
        return f"Error syncing: {str(e)}"

# --- Monitoring Tools ---

@mcp.tool()
async def usage(target: str | None = None) -> dict[str, Any]:
    """Get system resource usage (CPU, RAM, Disk)."""
    try:
        return await monitoring.usage(ssh, target)
    except Exception as e:
        return {"error": str(e), "target": target}

@mcp.tool()
async def logs(path: str, lines: int = 50, grep: str | None = None, target: str | None = None) -> str:
    """Read recent logs from a file (safer than 'read')."""
    try:
        return await monitoring.logs(ssh, path, lines, grep, target)
    except Exception as e:
        return f"Error reading logs: {str(e)}"

@mcp.tool()
async def ps(sort_by: str = "cpu", limit: int = 10, target: str | None = None) -> str:
    """List top processes consuming resources."""
    try:
        return await monitoring.ps(ssh, sort_by, limit, target)
    except Exception as e:
        return f"Error listing processes: {str(e)}"

# --- Docker Tools ---

@mcp.tool()
async def docker_ps(all: bool = False, target: str | None = None) -> dict[str, Any]:
    """List Docker containers."""
    try:
        return await docker.docker_ps(ssh, all, target)
    except Exception as e:
        return {"error": str(e), "target": target, "all": all}

@mcp.tool()
async def docker_logs(container_id: str, lines: int = 50, target: str | None = None) -> str:
    """Get logs for a specific container."""
    try:
        return await docker.docker_logs(ssh, container_id, lines, target)
    except Exception as e:
        return f"Error getting docker logs: {str(e)}"

@mcp.tool()
async def docker_op(container_id: str, action: str, target: str | None = None) -> str:
    """Perform action (start/stop/restart) on a container."""
    try:
        return await docker.docker_op(ssh, container_id, action, target)
    except Exception as e:
        return f"Error performing docker action: {str(e)}"

# --- Network Tools ---

@mcp.tool()
async def net_stat(port: int | None = None, target: str | None = None) -> dict[str, Any]:
    """Check for listening ports (uses ss or netstat)."""
    try:
        return await network.net_stat(ssh, port, target)
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

@mcp.tool()
async def net_dump(interface: str = "any", count: int = 20, filter: str = "", target: str | None = None) -> str:
    """Capture network traffic (tcpdump)."""
    try:
        return await network.net_dump(ssh, interface, count, filter, target)
    except Exception as e:
        return f"Error capturing traffic: {str(e)}"

@mcp.tool()
async def curl(url: str, method: str = "GET", target: str | None = None) -> str:
    """Check URL connectivity."""
    try:
        return await network.curl(ssh, url, method, target)
    except Exception as e:
        return f"Error running curl: {str(e)}"

if __name__ == "__main__":
    mcp.run()

