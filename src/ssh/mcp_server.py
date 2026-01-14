from __future__ import annotations

from mcp.server.fastmcp import FastMCP, Context
from .ssh_manager import SSHManager
from .session_store import SessionStore
from .tools import files, system, monitoring, docker, network
from .tools import services_universal, db, pkg
from .tools import net_debug, diagnostics, files_advanced
from .tools import bulk
from .tools import outage_prevention
import uvicorn
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
    """List Docker containers."""
    manager = await get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "all": all}
    try:
        return await docker.docker_ps(manager, all, target)
    except Exception as e:
        return {"error": str(e), "target": target, "all": all}

@mcp.tool()
async def docker_logs(ctx: Context, container_id: str, lines: int = 50, target: str = "primary") -> str:
    """Get logs for a specific container."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await docker.docker_logs(manager, container_id, lines, target)
    except Exception as e:
        return f"Error getting docker logs: {str(e)}"

@mcp.tool()
async def docker_op(ctx: Context, container_id: str, action: str, target: str = "primary") -> str:
    """Perform action (start/stop/restart) on a container."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await docker.docker_op(manager, container_id, action, target)
    except Exception as e:
        return f"Error performing docker action: {str(e)}"

@mcp.tool()
async def docker_ip(ctx: Context, container_name: str, target: str = "primary") -> dict[str, Any]:
    """Get the IP address(es) of a Docker container."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await docker.docker_ip(manager, container_name, target)

@mcp.tool()
async def docker_find_by_ip(ctx: Context, ip_address: str, target: str = "primary") -> dict[str, Any]:
    """Find which Docker container has a specific IP address."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await docker.docker_find_by_ip(manager, ip_address, target)

@mcp.tool()
async def docker_networks(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """List all Docker networks and their containers."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await docker.docker_networks(manager, target)

# --- Network Tools ---

@mcp.tool()
async def net_stat(ctx: Context, port: int | None = None, target: str = "primary") -> dict[str, Any]:
    """Check for listening ports (uses ss or netstat)."""
    manager = await get_session_manager(ctx)
    if not manager:
        return {"error": "not_connected", "target": target, "port": port}
    try:
        return await network.net_stat(manager, port, target)
    except Exception as e:
        return {"error": str(e), "target": target, "port": port}

@mcp.tool()
async def net_dump(ctx: Context, interface: str = "any", count: int = 20, filter: str = "", target: str = "primary") -> str:
    """Capture network traffic (tcpdump)."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await network.net_dump(manager, interface, count, filter, target)
    except Exception as e:
        return f"Error capturing traffic: {str(e)}"

@mcp.tool()
async def curl(ctx: Context, url: str, method: str = "GET", target: str = "primary") -> str:
    """Check URL connectivity."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    try:
        return await network.curl(manager, url, method, target)
    except Exception as e:
        return f"Error running curl: {str(e)}"

# --- Service Tools ---

@mcp.tool()
async def inspect_service(ctx: Context, name: str, target: str = "primary") -> dict[str, Any]:
    """Inspect a service or container status. Auto-detects Docker/Systemd/OpenRC."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await services_universal.inspect_service(manager, name, target)

@mcp.tool()
async def list_services(ctx: Context, failed_only: bool = False, target: str = "primary") -> dict[str, Any]:
    """List system services (Systemd/OpenRC)."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await services_universal.list_services(manager, failed_only, target)

@mcp.tool()
async def fetch_logs(ctx: Context, service_name: str, lines: int = 100, error_only: bool = False, target: str = "primary") -> str:
    """Fetch logs for a service/container. Auto-detects source (docker/journald/files)."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await services_universal.fetch_logs(manager, service_name, lines, error_only, target)

@mcp.tool()
async def service_action(ctx: Context, name: str, action: str, target: str = "primary") -> str:
    """Perform action (start/stop/restart/reload) on a service or container."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await services_universal.service_action(manager, name, action, target)

# --- Database Tools ---

@mcp.tool()
async def list_db_containers(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Find Docker containers that look like databases (postgres, mysql, scylla, etc)."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await db.list_db_containers(manager, target)

@mcp.tool()
async def db_schema(ctx: Context, container_name: str, db_type: str, database: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Get database schema (tables). Supports: postgres, mysql, scylladb."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await db.db_schema(manager, container_name, db_type, database, target)

@mcp.tool()
async def db_describe_table(ctx: Context, container_name: str, db_type: str, table: str, database: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Describe a specific table's structure."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await db.db_describe_table(manager, container_name, db_type, table, database, target)

@mcp.tool()
async def db_query(ctx: Context, container_name: str, db_type: str, query: str, database: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Execute a SQL/CQL query inside a database container."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await db.db_query(manager, container_name, db_type, query, database, target)

# --- Package Manager Tools ---

@mcp.tool()
async def install_package(ctx: Context, packages: list[str], target: str = "primary") -> dict[str, Any]:
    """Install packages using the system's package manager (apt/apk/dnf)."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await pkg.install_package(manager, packages, target)

@mcp.tool()
async def remove_package(ctx: Context, packages: list[str], target: str = "primary") -> dict[str, Any]:
    """Remove packages using the system's package manager."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await pkg.remove_package(manager, packages, target)

@mcp.tool()
async def search_package(ctx: Context, query: str, target: str = "primary") -> dict[str, Any]:
    """Search for packages matching a query."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await pkg.search_package(manager, query, target)

@mcp.tool()
async def list_installed(ctx: Context, grep: str | None = None, target: str = "primary") -> dict[str, Any]:
    """List installed packages, optionally filtering by name."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await pkg.list_installed(manager, grep, target)

# --- Connectivity Tools ---

@mcp.tool()
async def test_connection(ctx: Context, host: str, port: int, timeout: int = 2, target: str = "primary") -> dict[str, Any]:
    """Test TCP connectivity from target to a host:port. Uses nc, bash, or python."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await net_debug.test_connection(manager, host, port, timeout, target)

@mcp.tool()
async def check_port_owner(ctx: Context, port: int, target: str = "primary") -> dict[str, Any]:
    """Find which process is listening on a specific port."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await net_debug.check_port_owner(manager, port, target)

@mcp.tool()
async def scan_ports(ctx: Context, host: str, ports: list[int], timeout: int = 1, target: str = "primary") -> dict[str, Any]:
    """Quick scan multiple ports on a host."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await net_debug.scan_ports(manager, host, ports, timeout, target)

# --- Diagnostics Tools ---

@mcp.tool()
async def list_scheduled_tasks(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Get unified view of cron jobs and systemd timers."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await diagnostics.list_scheduled_tasks(manager, target)

@mcp.tool()
async def hunt_zombies(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Find zombie (defunct) processes."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await diagnostics.hunt_zombies(manager, target)

@mcp.tool()
async def hunt_io_hogs(ctx: Context, limit: int = 10, target: str = "primary") -> dict[str, Any]:
    """Find processes with high I/O wait or in D state."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await diagnostics.hunt_io_hogs(manager, limit, target)

@mcp.tool()
async def check_system_health(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Quick system health overview (load, memory, disk, uptime)."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await diagnostics.check_system_health(manager, target)

@mcp.tool()
async def check_oom_events(ctx: Context, lines: int = 20, target: str = "primary") -> str:
    """Check for recent Out-Of-Memory kill events in kernel logs."""
    manager = await get_session_manager(ctx)
    if not manager: return "Error: Not connected."
    return await diagnostics.check_oom_events(manager, lines, target)

# --- Advanced File Tools ---

@mcp.tool()
async def find_large_files(ctx: Context, path: str = "/", limit: int = 10, min_size: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Find the largest files recursively. Use min_size like '100M' or '1G'."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await files_advanced.find_large_files(manager, path, limit, min_size, target)

@mcp.tool()
async def find_large_folders(ctx: Context, path: str = "/", limit: int = 10, max_depth: int = 2, target: str = "primary") -> dict[str, Any]:
    """Find the largest folders. max_depth controls how deep to analyze."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await files_advanced.find_large_folders(manager, path, limit, max_depth, target)

@mcp.tool()
async def disk_usage_summary(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Get disk usage for all mounted filesystems."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await files_advanced.disk_usage_summary(manager, target)

@mcp.tool()
async def find_old_files(ctx: Context, path: str, days: int = 30, limit: int = 20, target: str = "primary") -> dict[str, Any]:
    """Find files older than N days. Useful for stale logs or backups."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await files_advanced.find_old_files(manager, path, days, limit, target)

@mcp.tool()
async def find_recently_modified(ctx: Context, path: str, minutes: int = 60, limit: int = 20, target: str = "primary") -> dict[str, Any]:
    """Find files modified in last N minutes. Useful during incidents."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await files_advanced.find_recently_modified(manager, path, minutes, limit, target)

# --- Fleet Bulk Operations ---

@mcp.tool()
async def bulk_run(ctx: Context, command: str, targets: list[str]) -> dict[str, Any]:
    """Run the same command on multiple targets simultaneously."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_run(manager, command, targets)

@mcp.tool()
async def bulk_read(ctx: Context, path: str, targets: list[str]) -> dict[str, Any]:
    """Read the same file from multiple targets. Useful for comparing configs."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_read(manager, path, targets)

@mcp.tool()
async def bulk_write(ctx: Context, path: str, content: str, targets: list[str]) -> dict[str, Any]:
    """Write the same content to a file on multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_write(manager, path, content, targets)

@mcp.tool()
async def bulk_edit(ctx: Context, path: str, old_text: str, new_text: str, targets: list[str]) -> dict[str, Any]:
    """Edit the same file on multiple targets (find/replace). Great for mass config updates."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_edit(manager, path, old_text, new_text, targets)

@mcp.tool()
async def bulk_docker_ps(ctx: Context, all: bool, targets: list[str]) -> dict[str, Any]:
    """Get container inventory from multiple targets. Cluster-wide container view."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_docker_ps(manager, all, targets)

@mcp.tool()
async def bulk_usage(ctx: Context, targets: list[str]) -> dict[str, Any]:
    """Get resource usage (CPU/RAM/Disk) from multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_usage(manager, targets)

@mcp.tool()
async def bulk_service(ctx: Context, name: str, action: str, targets: list[str]) -> dict[str, Any]:
    """Perform service action (start/stop/restart) on multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_service(manager, name, action, targets)

@mcp.tool()
async def bulk_install(ctx: Context, packages: list[str], targets: list[str]) -> dict[str, Any]:
    """Install packages on multiple targets. Auto-detects apt/apk/dnf per target."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_install(manager, packages, targets)

@mcp.tool()
async def bulk_connectivity(ctx: Context, host: str, port: int, targets: list[str], timeout: int = 2) -> dict[str, Any]:
    """Test if multiple targets can reach a specific host:port."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_connectivity(manager, host, port, targets, timeout)

@mcp.tool()
async def bulk_health(ctx: Context, targets: list[str]) -> dict[str, Any]:
    """Get system health overview from multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_health(manager, targets)

@mcp.tool()
async def bulk_zombies(ctx: Context, targets: list[str]) -> dict[str, Any]:
    """Hunt zombie processes across multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_zombies(manager, targets)

@mcp.tool()
async def bulk_disk(ctx: Context, targets: list[str]) -> dict[str, Any]:
    """Get disk usage summary from multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_disk(manager, targets)

@mcp.tool()
async def bulk_remove_package(ctx: Context, packages: list[str], targets: list[str]) -> dict[str, Any]:
    """Remove packages from multiple targets. Auto-detects apt/apk/dnf."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_remove_package(manager, packages, targets)

@mcp.tool()
async def bulk_db_query(ctx: Context, container_name: str, db_type: str, query: str, database: str | None, targets: list[str]) -> dict[str, Any]:
    """Execute same SQL/CQL query on database containers across multiple hosts."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_db_query(manager, container_name, db_type, query, database, targets)

@mcp.tool()
async def bulk_oom_check(ctx: Context, lines: int, targets: list[str]) -> dict[str, Any]:
    """Check for OOM kill events across multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_oom_check(manager, lines, targets)

@mcp.tool()
async def bulk_find_large_files(ctx: Context, path: str, limit: int, targets: list[str], min_size: str | None = None) -> dict[str, Any]:
    """Find largest files across multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_find_large_files(manager, path, limit, targets, min_size)

@mcp.tool()
async def bulk_ssl_check(ctx: Context, host: str, port: int, targets: list[str]) -> dict[str, Any]:
    """Check SSL cert expiry from multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_ssl_check(manager, host, port, targets)

@mcp.tool()
async def bulk_dns_check(ctx: Context, hostname: str, targets: list[str]) -> dict[str, Any]:
    """Verify DNS resolution from multiple targets."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await bulk.bulk_dns_check(manager, hostname, targets)

# --- Outage Prevention Tools ---

@mcp.tool()
async def check_ssl_cert(ctx: Context, host: str, port: int = 443, target: str = "primary") -> dict[str, Any]:
    """Check SSL certificate details and expiry. Returns days until expiration."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await outage_prevention.check_ssl_cert(manager, host, port, target)

@mcp.tool()
async def check_dns(ctx: Context, hostname: str, target: str = "primary") -> dict[str, Any]:
    """Check if hostname resolves correctly from target. Returns resolved IPs."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await outage_prevention.check_dns(manager, hostname, target)

@mcp.tool()
async def check_ulimits(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Check resource limits (open files, max processes). Warns if near limits."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await outage_prevention.check_ulimits(manager, target)

@mcp.tool()
async def check_network_errors(ctx: Context, target: str = "primary") -> dict[str, Any]:
    """Check network interfaces for packet drops and errors."""
    manager = await get_session_manager(ctx)
    if not manager: return {"error": "Not connected"}
    return await outage_prevention.check_network_errors(manager, target)

# --- App Entry Point ---
# This module is imported by server_all.py which handles the actual HTTP transport
# For standalone usage, use: uvicorn ssh.server_all:app --host 0.0.0.0 --port 8000
