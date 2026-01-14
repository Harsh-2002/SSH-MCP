from __future__ import annotations

from mcp.server.fastmcp import FastMCP, Context
from .ssh_manager import SSHManager
from .session_store import SessionStore
from .tools import files, system, monitoring, docker, network
from .tools import services_universal, db
import os
import logging
from typing import Any
from contextlib import asynccontextmanager


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# Configuration
_SESSION_HEADER = os.getenv("SSH_MCP_SESSION_HEADER", "X-Session-Key")
_SESSION_TIMEOUT = int(os.getenv("SSH_MCP_SESSION_TIMEOUT", "300"))

# Global State (Legacy/Simple Mode)
_GLOBAL_STATE = _env_truthy("SSH_MCP_GLOBAL_STATE", default=False)
_GLOBAL_MANAGER: SSHManager | None = SSHManager() if _GLOBAL_STATE else None

# Smart Session Store (Header-based Mode)
# Initialized immediately, started in lifespan
_SESSION_STORE = SessionStore(timeout_seconds=_SESSION_TIMEOUT)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ssh-mcp-server")


@asynccontextmanager
async def lifespan(server: Any):
    """Manage background tasks (SessionStore cleanup)."""
    # Ensure store is started
    if _SESSION_STORE:
        await _SESSION_STORE.start()
    
    try:
        yield
    finally:
        if _SESSION_STORE:
            await _SESSION_STORE.stop()


# Initialize FastMCP WITHOUT lifespan - lifespan is managed by server_all.py Starlette app
# Passing lifespan to FastMCP would cause premature SessionStore cleanup
mcp = FastMCP("ssh-mcp")


# --- Session Management ---

async def get_session_manager(ctx: Context) -> SSHManager | None:
    """Return the SSH manager for this request.

    Strategy:
    1. Global: If SSH_MCP_GLOBAL_STATE is true, use one shared manager.
    2. Header Cache: If X-Session-Key is present, use Smart Session Store.
    3. Session: Default to per-session isolation.
    """
    # 1. Global State Override
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER

    # 2. Smart Session Header Strategy
    if _SESSION_STORE and ctx.request_context:
        # Access the raw ASGI scope headers from the request object
        # request_context.request is the Starlette Request
        request = ctx.request_context.request
        if request:
            header_value = request.headers.get(_SESSION_HEADER)
            if header_value:
                return await _SESSION_STORE.get(header_value)

    # 3. Default Session Isolation
    return getattr(ctx.session, "ssh_manager", None)

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
    manager = await get_session_manager(ctx)
    if manager is None:
        # Per-session mode: create a manager for this session.
        manager = SSHManager()
        setattr(ctx.session, "ssh_manager", manager)

    try:
        result = await manager.connect(host, username, port, private_key_path, password, alias, via)
        return result
    except Exception as e:
        return f"Error connecting: {str(e)}"

@mcp.tool()
async def disconnect(ctx: Context, alias: str | None = None) -> str:
    """Disconnect session."""
    manager = await get_session_manager(ctx)
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
    # Use the global manager if enabled, otherwise create a lightweight instance.
    temp_manager = _GLOBAL_MANAGER or SSHManager()
    key = temp_manager.get_public_key()
    return f"```\n{key}\n```"

@mcp.tool()
async def sync(ctx: Context, source_node: str, source_path: str, dest_node: str, dest_path: str) -> str:
    """Stream file from source_node to dest_node efficiently."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await manager.sync(source_node, source_path, dest_node, dest_path)
    except Exception as e:
        return f"Error syncing: {str(e)}"

# --- File Tools ---

@mcp.tool()
async def read(ctx: Context, path: str, target: str = "primary") -> str:
    """Read a remote file."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.read_file(manager, path, target)

@mcp.tool()
async def write(ctx: Context, path: str, content: str, target: str = "primary") -> str:
    """Write content to a remote file (overwrite)."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.write_file(manager, path, content, target)

@mcp.tool()
async def edit(ctx: Context, path: str, old_text: str, new_text: str, target: str = "primary") -> str:
    """Smart replace text in a file. Errors if match is not unique."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.edit_file(manager, path, old_text, new_text, target)

@mcp.tool()
async def list_dir(ctx: Context, path: str, target: str = "primary") -> str:
    """List files in a directory (JSON format)."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await files.list_directory(manager, path, target)

# --- System Tools ---

@mcp.tool()
async def run(ctx: Context, command: str, target: str = "primary") -> str:
    """Execute a shell command."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.run_command(manager, command, target)

@mcp.tool()
async def info(ctx: Context, target: str = "primary") -> str:
    """Get OS/Kernel details."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await system.get_system_info(manager, target)

# --- Monitoring Tools ---

@mcp.tool()
async def usage(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Get system resource usage (CPU, RAM, Disk)."""
    manager = await get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target}
    try:
        return await monitoring.usage(manager, target)
    except Exception as e:
        return {"error": str(e), "target": target}

@mcp.tool()
async def logs(ctx: Context, path: str, lines: int = 50, grep: str | None = None, target: str = "primary") -> str:
    """Read recent logs from a file (safer than 'read')."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await monitoring.logs(manager, path, lines, grep, target)
    except Exception as e:
        return f"Error reading logs: {str(e)}"

@mcp.tool()
async def ps(ctx: Context, sort_by: str = "cpu", limit: int = 10, target: str = "primary") -> str:
    """List top processes consuming resources."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await monitoring.ps(manager, sort_by, limit, target)
    except Exception as e:
        return f"Error listing processes: {str(e)}"

# --- Docker Tools ---

@mcp.tool()
async def docker_ps(ctx: Context, all: bool = False, target: str = "primary") -> dict[str, Any]:
    """List Docker containers. Returns structured JSON with container info.
    
    For other docker operations, use the `run` tool:
    - Logs: run("docker logs <container>")
    - Start/Stop: run("docker start|stop|restart <container>")
    - Inspect: run("docker inspect <container>")
    - Exec: run("docker exec <container> <command>")
    - Networks: run("docker network ls")
    - Copy: run("docker cp <src> <dst>")
    """
    manager = await get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "all": all}
    try:
        return await docker.docker_ps(manager, all, target)
    except Exception as e:
        return {"error": str(e), "target": target, "all": all}

# --- Network Tools ---

@mcp.tool()
async def net_stat(ctx: Context, port: int | None = None, target: str = "primary") -> dict[str, Any]:
    """Check for listening ports (uses ss or netstat). Returns structured JSON.
    
    For other network operations, use the `run` tool:
    - Connectivity: run("nc -zv host port") or run("ping host")
    - DNS: run("dig domain") or run("nslookup domain")
    - Traffic: run("tcpdump -i any -c 20")
    - Curl: run("curl -s url")
    """
    manager = await get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "port": port}
    try:
        return await network.net_stat(manager, port, target)
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

# --- Service Tools ---

@mcp.tool()
async def list_services(ctx: Context, failed_only: bool = False, target: str = "primary") -> dict[str, Any]:
    """List system services (Systemd/OpenRC). Returns structured JSON.
    
    For service operations, use the `run` tool:
    - Status: run("systemctl status <service>")
    - Start/Stop: run("systemctl start|stop|restart <service>")
    - Logs: run("journalctl -u <service> -n 100")
    - Enable/Disable: run("systemctl enable|disable <service>")
    """
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await services_universal.list_services(manager, failed_only, target)

# --- Database Tools ---

@mcp.tool()
async def db_query(
    ctx: Context, 
    container_name: str, 
    db_type: str, 
    query: str, 
    database: str | None = None, 
    username: str | None = None,
    password: str | None = None,
    target: str = "primary"
) -> dict[str, Any]:
    """Execute a SQL/CQL query inside a database container.
    
    This tool handles credentials securely via environment variables (not command line).
    Supports: postgres, mysql, scylladb.
    
    Args:
        container_name: Docker container name
        db_type: "postgres", "mysql", or "scylladb"
        query: SQL/CQL query to execute
        database: Database name (optional for scylladb)
        username: Database username (optional, uses defaults if not provided)
        password: Database password (optional, uses defaults if not provided)
        target: SSH connection alias
    """
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await db.db_query(manager, container_name, db_type, query, database, username, password, target)


# --- App Entry Point ---
# This module is imported by server_all.py which handles the actual HTTP transport
# For standalone usage, use: uvicorn ssh_mcp.server_all:app --host 0.0.0.0 --port 8000

