"""Universal service and log management tools.

Supports: Systemd, OpenRC, Docker containers.
"""
import json
import logging
from typing import Any

from .base import detect_init_system, is_docker_container, docker_available

logger = logging.getLogger("ssh-mcp")


async def inspect_service(manager, name: str, target: str = "primary") -> dict[str, Any]:
    """Inspect a service/container status universally.
    
    Auto-detects if `name` is a Docker container or a system service (Systemd/OpenRC).
    
    Returns:
        {
            "name": str,
            "type": "docker"|"systemd"|"openrc"|"unknown",
            "status": "running"|"stopped"|"failed"|"unknown",
            "details": str,  # Raw status output
            "logs": str      # Last 20 log lines
        }
    """
    result = {
        "name": name,
        "type": "unknown",
        "status": "unknown",
        "details": "",
        "logs": ""
    }
    
    # 1. Check if it's a Docker container
    if await docker_available(manager, target):
        if await is_docker_container(manager, name, target):
            result["type"] = "docker"
            
            # Get container status
            status_cmd = f"docker inspect --format '{{{{.State.Status}}}}' {name} 2>/dev/null"
            status = (await manager.run_command(status_cmd, target)).strip()
            result["status"] = status if status else "unknown"
            
            # Get details
            details_cmd = f"docker inspect --format 'Image: {{{{.Config.Image}}}}\\nCreated: {{{{.Created}}}}\\nRestarts: {{{{.RestartCount}}}}' {name} 2>/dev/null"
            result["details"] = await manager.run_command(details_cmd, target)
            
            # Get logs
            logs_cmd = f"docker logs --tail 20 {name} 2>&1"
            result["logs"] = await manager.run_command(logs_cmd, target)
            
            return result
    
    # 2. Check system service
    init_system = await detect_init_system(manager, target)
    
    if init_system == "systemd":
        result["type"] = "systemd"
        
        # Get status
        status_cmd = f"systemctl is-active {name} 2>/dev/null || echo 'unknown'"
        status = (await manager.run_command(status_cmd, target)).strip()
        result["status"] = status
        
        # Get details
        details_cmd = f"systemctl status {name} --no-pager -l 2>&1 | head -20"
        result["details"] = await manager.run_command(details_cmd, target)
        
        # Get logs
        logs_cmd = f"journalctl -u {name} -n 20 --no-pager 2>/dev/null || echo 'No journal logs'"
        result["logs"] = await manager.run_command(logs_cmd, target)
        
    elif init_system == "openrc":
        result["type"] = "openrc"
        
        # Get status
        status_cmd = f"rc-service {name} status 2>&1"
        status_output = await manager.run_command(status_cmd, target)
        if "started" in status_output.lower():
            result["status"] = "running"
        elif "stopped" in status_output.lower():
            result["status"] = "stopped"
        else:
            result["status"] = "unknown"
        
        result["details"] = status_output
        
        # OpenRC typically logs to /var/log/messages or service-specific files
        logs_cmd = f"tail -20 /var/log/{name}.log 2>/dev/null || tail -20 /var/log/messages 2>/dev/null | grep -i {name} || echo 'No logs found'"
        result["logs"] = await manager.run_command(logs_cmd, target)
    
    return result


async def list_services(manager, failed_only: bool = False, target: str = "primary") -> dict[str, Any]:
    """List system services.
    
    Returns:
        {"init_system": str, "services": [...]}
    """
    init_system = await detect_init_system(manager, target)
    result = {"init_system": init_system, "services": []}
    
    if init_system == "systemd":
        if failed_only:
            cmd = "systemctl list-units --type=service --state=failed --no-pager --no-legend"
        else:
            cmd = "systemctl list-units --type=service --state=running --no-pager --no-legend"
        output = await manager.run_command(cmd, target)
        for line in output.strip().split("\n"):
            if line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    result["services"].append({
                        "unit": parts[0],
                        "state": parts[2] if len(parts) > 2 else "unknown"
                    })
    
    elif init_system == "openrc":
        cmd = "rc-status --all 2>/dev/null"
        output = await manager.run_command(cmd, target)
        result["services"] = [{"raw": output}]  # OpenRC output is less structured
    
    return result


async def fetch_logs(manager, service_name: str, lines: int = 100, 
                     error_only: bool = False, target: str = "primary") -> str:
    """Fetch logs for a service, auto-detecting source (docker/journald/files).
    
    Args:
        service_name: Name of service or container.
        lines: Maximum lines to return.
        error_only: If True, filter for error/warning patterns.
        
    Returns:
        Log content as string.
    """
    logs = ""
    
    # 1. Try Docker
    if await docker_available(manager, target):
        if await is_docker_container(manager, service_name, target):
            cmd = f"docker logs --tail {lines} {service_name} 2>&1"
            logs = await manager.run_command(cmd, target)
            if error_only and logs:
                # Filter for common error patterns
                lines_list = logs.split("\n")
                filtered = [l for l in lines_list if any(p in l.lower() for p in ["error", "err", "fatal", "warn", "fail", "exception"])]
                logs = "\n".join(filtered) if filtered else "(No errors found in logs)"
            return logs
    
    # 2. Try journalctl
    init_system = await detect_init_system(manager, target)
    if init_system == "systemd":
        grep_flag = "--grep='error|fail|warn'" if error_only else ""
        cmd = f"journalctl -u {service_name} -n {lines} --no-pager {grep_flag} 2>/dev/null"
        logs = await manager.run_command(cmd, target)
        if logs.strip():
            return logs
    
    # 3. Try common log file paths
    paths_to_try = [
        f"/var/log/{service_name}.log",
        f"/var/log/{service_name}/{service_name}.log",
        f"/var/log/{service_name}/error.log",
    ]
    for path in paths_to_try:
        check = await manager.run_command(f"test -f {path} && echo 'exists'", target)
        if "exists" in check:
            if error_only:
                cmd = f"grep -iE 'error|fail|warn' {path} | tail -{lines}"
            else:
                cmd = f"tail -{lines} {path}"
            logs = await manager.run_command(cmd, target)
            if logs.strip():
                return logs
    
    return f"No logs found for '{service_name}'"


async def service_action(manager, name: str, action: str, target: str = "primary") -> str:
    """Perform an action on a service (start/stop/restart/reload).
    
    Supports Docker containers and Systemd services.
    """
    if action not in ("start", "stop", "restart", "reload"):
        return f"Invalid action: {action}. Use start/stop/restart/reload."
    
    # Check Docker first
    if await docker_available(manager, target):
        if await is_docker_container(manager, name, target):
            if action == "reload":
                return "Docker containers do not support reload. Use restart."
            cmd = f"docker {action} {name} 2>&1"
            return await manager.run_command(cmd, target)
    
    # Systemd
    init_system = await detect_init_system(manager, target)
    if init_system == "systemd":
        cmd = f"systemctl {action} {name} 2>&1"
        return await manager.run_command(cmd, target)
    elif init_system == "openrc":
        cmd = f"rc-service {name} {action} 2>&1"
        return await manager.run_command(cmd, target)
    
    return f"Cannot perform action: unknown init system on {target}"
