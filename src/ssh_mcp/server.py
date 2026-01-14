from mcp.server.fastmcp import FastMCP
from .ssh_manager import SSHManager
from .tools import files, system
import logging

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
    password: str | None = None
) -> str:
    """Connect to a remote server via SSH."""
    try:
        return await ssh.connect(host, username, port, private_key_path, password)
    except Exception as e:
        return f"Error connecting: {str(e)}"

@mcp.tool()
async def run(command: str) -> str:
    """Execute a shell command."""
    try:
        return await system.run_command(ssh, command)
    except Exception as e:
        return f"Error executing command: {str(e)}"

@mcp.tool()
async def info() -> str:
    """Get OS/Kernel details."""
    try:
        return await system.get_system_info(ssh)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def disconnect() -> str:
    """Disconnect session."""
    try:
        return await ssh.disconnect()
    except Exception as e:
        return f"Error disconnecting: {str(e)}"

@mcp.tool()
async def identity() -> str:
    """Get the system's public SSH key to add to authorized_keys on remote targets."""
    return ssh.get_public_key()

# --- File Tools ---

@mcp.tool()
async def read(path: str) -> str:
    """Read a remote file."""
    try:
        return await files.read_file(ssh, path)
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp.tool()
async def write(path: str, content: str) -> str:
    """Write content to a remote file."""
    try:
        return await files.write_file(ssh, path, content)
    except Exception as e:
        return f"Error writing file: {str(e)}"

@mcp.tool()
async def edit(path: str, old_text: str, new_text: str) -> str:
    """Smart replace text in a file."""
    try:
        return await files.edit_file(ssh, path, old_text, new_text)
    except Exception as e:
        return f"Error editing file: {str(e)}"

@mcp.tool()
async def list(path: str) -> str:
    """List files in a directory."""
    try:
        return await files.list_directory(ssh, path)
    except Exception as e:
        return f"Error listing directory: {str(e)}"

if __name__ == "__main__":
    mcp.run()
