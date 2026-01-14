"""Fleet-wide bulk operations.

Run commands, edit files, and manage services across multiple hosts simultaneously.
Uses asyncio.gather for true parallel execution.
"""
import asyncio
import logging
from typing import Any

from .files import read_file, write_file, edit_file
from .system import run_command
from .monitoring import usage as system_usage
from .docker import docker_ps
from .services_universal import service_action as single_service_action
from .pkg import install_package as single_install, remove_package as single_remove
from .net_debug import test_connection as single_test_connection
from .diagnostics import check_system_health as single_health, hunt_zombies as single_zombies, check_oom_events as single_oom
from .files_advanced import disk_usage_summary as single_disk, find_large_files as single_large_files
from .db import db_query as single_db_query
from .outage_prevention import check_ssl_cert as single_ssl, check_dns as single_dns

logger = logging.getLogger("ssh-mcp")


async def _run_on_target(coro, target: str) -> dict[str, Any]:
    """Wrapper to catch exceptions per-target."""
    try:
        result = await coro
        return {"target": target, "status": "success", "result": result}
    except Exception as e:
        return {"target": target, "status": "error", "error": str(e)}


async def bulk_run(manager, command: str, targets: list[str]) -> dict[str, Any]:
    """Run the same command on multiple targets simultaneously.
    
    Args:
        command: Shell command to execute.
        targets: List of SSH connection aliases.
        
    Returns:
        {"results": [{"target": str, "status": str, "result": str | error: str}]}
    """
    tasks = [_run_on_target(run_command(manager, command, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"command": command, "results": list(results)}


async def bulk_read(manager, path: str, targets: list[str]) -> dict[str, Any]:
    """Read the same file from multiple targets.
    
    Useful for comparing configs across a cluster.
    """
    tasks = [_run_on_target(read_file(manager, path, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"path": path, "results": list(results)}


async def bulk_write(manager, path: str, content: str, targets: list[str]) -> dict[str, Any]:
    """Write the same content to a file on multiple targets.
    
    Useful for deploying configs across a cluster.
    """
    tasks = [_run_on_target(write_file(manager, path, content, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"path": path, "results": list(results)}


async def bulk_edit(manager, path: str, old_text: str, new_text: str, 
                    targets: list[str]) -> dict[str, Any]:
    """Edit the same file on multiple targets (find/replace).
    
    Example: Change nginx worker_processes on all web servers.
    """
    tasks = [_run_on_target(edit_file(manager, path, old_text, new_text, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"path": path, "old_text": old_text, "new_text": new_text, "results": list(results)}


async def bulk_docker_ps(manager, all: bool, targets: list[str]) -> dict[str, Any]:
    """Get container inventory from multiple targets.
    
    Returns a cluster-wide view of all running containers.
    """
    tasks = [_run_on_target(docker_ps(manager, all, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"all": all, "results": list(results)}


async def bulk_usage(manager, targets: list[str]) -> dict[str, Any]:
    """Get resource usage (CPU/RAM/Disk) from multiple targets.
    
    Useful for fleet-wide resource monitoring dashboard.
    """
    tasks = [_run_on_target(system_usage(manager, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"results": list(results)}


async def bulk_service(manager, name: str, action: str, targets: list[str]) -> dict[str, Any]:
    """Perform service action on multiple targets.
    
    Example: Restart nginx on all web servers.
    """
    tasks = [_run_on_target(single_service_action(manager, name, action, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"service": name, "action": action, "results": list(results)}


async def bulk_install(manager, packages: list[str], targets: list[str]) -> dict[str, Any]:
    """Install packages on multiple targets.
    
    Handles different package managers (apt/apk/dnf) per target automatically.
    """
    tasks = [_run_on_target(single_install(manager, packages, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"packages": packages, "results": list(results)}


async def bulk_connectivity(manager, host: str, port: int, targets: list[str],
                            timeout: int = 2) -> dict[str, Any]:
    """Test if multiple targets can reach a specific host:port.
    
    Example: Verify all app servers can reach the database.
    """
    tasks = [_run_on_target(single_test_connection(manager, host, port, timeout, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"host": host, "port": port, "results": list(results)}


async def bulk_health(manager, targets: list[str]) -> dict[str, Any]:
    """Get system health overview from multiple targets."""
    tasks = [_run_on_target(single_health(manager, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"results": list(results)}


async def bulk_zombies(manager, targets: list[str]) -> dict[str, Any]:
    """Hunt zombie processes across multiple targets."""
    tasks = [_run_on_target(single_zombies(manager, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"results": list(results)}


async def bulk_disk(manager, targets: list[str]) -> dict[str, Any]:
    """Get disk usage summary from multiple targets."""
    tasks = [_run_on_target(single_disk(manager, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"results": list(results)}


async def bulk_remove_package(manager, packages: list[str], targets: list[str]) -> dict[str, Any]:
    """Remove packages from multiple targets.
    
    Handles different package managers (apt/apk/dnf) per target automatically.
    """
    tasks = [_run_on_target(single_remove(manager, packages, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"packages": packages, "results": list(results)}


async def bulk_db_query(manager, container_name: str, db_type: str, query: str,
                        database: str | None, targets: list[str]) -> dict[str, Any]:
    """Execute the same SQL/CQL query on database containers across multiple hosts.
    
    Useful for checking replication, comparing data, or fleet-wide schema updates.
    """
    tasks = [_run_on_target(single_db_query(manager, container_name, db_type, query, database, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"query": query, "db_type": db_type, "results": list(results)}


async def bulk_oom_check(manager, lines: int, targets: list[str]) -> dict[str, Any]:
    """Check for OOM (Out of Memory) kill events across multiple targets.
    
    Essential for catching memory pressure issues fleet-wide.
    """
    tasks = [_run_on_target(single_oom(manager, lines, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"results": list(results)}


async def bulk_find_large_files(manager, path: str, limit: int, targets: list[str],
                                 min_size: str | None = None) -> dict[str, Any]:
    """Find largest files across multiple targets.
    
    Helps identify disk space hogs fleet-wide.
    """
    tasks = [_run_on_target(single_large_files(manager, path, limit, min_size, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"path": path, "results": list(results)}


async def bulk_ssl_check(manager, host: str, port: int, targets: list[str]) -> dict[str, Any]:
    """Check SSL certificate expiry from multiple targets.
    
    Useful for verifying cert visibility from all nodes or checking multiple endpoints.
    """
    tasks = [_run_on_target(single_ssl(manager, host, port, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"host": host, "port": port, "results": list(results)}


async def bulk_dns_check(manager, hostname: str, targets: list[str]) -> dict[str, Any]:
    """Verify DNS resolution from multiple targets.
    
    Essential: Ensures all nodes can resolve critical hostnames.
    """
    tasks = [_run_on_target(single_dns(manager, hostname, t), t) for t in targets]
    results = await asyncio.gather(*tasks)
    return {"hostname": hostname, "results": list(results)}


