from __future__ import annotations

from ..ssh_manager import SSHManager

import json
from typing import Any


async def check_tool_availability(manager: SSHManager, tool: str, target: str | None = None) -> bool:
    """Checks if a command-line tool is available on the remote system."""
    check_cmd = f"command -v {tool} >/dev/null 2>&1 && echo 'present' || echo 'missing'"
    output = await manager.run(check_cmd, target=target)
    return "present" in output


async def docker_ps(manager: SSHManager, all: bool = False, target: str | None = None) -> dict[str, Any]:
    """List Docker containers as structured data."""
    if not await check_tool_availability(manager, "docker", target=target):
        return {"error": "docker_not_found", "target": target}

    flag = "-a" if all else ""
    res = await manager.run_result(f"docker ps {flag} --no-trunc --format '{{{{json .}}}}'", target=target)

    containers: list[dict[str, Any]] = []
    for line in res["stdout"].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except Exception:
            containers.append({"raw": line})

    return {"target": res["target"], "containers": containers, "all": all}

async def docker_logs(manager: SSHManager, container_id: str, lines: int = 50, target: str | None = None) -> str:
    """Get logs for a specific container."""
    if not await check_tool_availability(manager, "docker", target=target):
        return "Error: Docker command not found."
        
    cmd = f"docker logs --tail {lines} {container_id}"
    return await manager.run(cmd, target=target)

async def docker_op(manager: SSHManager, container_id: str, action: str, target: str | None = None) -> str:
    """
    Perform a lifecycle action on a container.
    Args:
        action: start, stop, restart
    """
    if action not in ["start", "stop", "restart"]:
        return "Error: Invalid action. Use start, stop, or restart."
        
    if not await check_tool_availability(manager, "docker", target=target):
        return "Error: Docker command not found."

    cmd = f"docker {action} {container_id}"
    return await manager.run(cmd, target=target)


async def docker_ip(manager: SSHManager, container_name: str, target: str | None = None) -> dict[str, Any]:
    """Get the IP address(es) of a Docker container.
    
    Returns:
        {"container": str, "networks": [{"name": str, "ip": str}], "error": str | None}
    """
    result = {
        "container": container_name,
        "networks": [],
        "error": None
    }
    
    if not await check_tool_availability(manager, "docker", target=target):
        result["error"] = "docker_not_found"
        return result
    
    # Get all network IPs for this container
    cmd = f"docker inspect --format '{{{{range $net, $conf := .NetworkSettings.Networks}}}}{{{{$net}}}}:{{{{$conf.IPAddress}}}}|{{{{end}}}}' {container_name} 2>/dev/null"
    output = await manager.run(cmd, target=target)
    
    if "Error" in output or not output.strip():
        result["error"] = f"Container '{container_name}' not found or not running"
        return result
    
    # Parse output: network1:ip1|network2:ip2|
    for part in output.strip().split("|"):
        if ":" in part:
            net, ip = part.split(":", 1)
            if ip:
                result["networks"].append({"name": net, "ip": ip})
    
    return result


async def docker_find_by_ip(manager: SSHManager, ip_address: str, target: str | None = None) -> dict[str, Any]:
    """Find which Docker container has a specific IP address.
    
    Returns:
        {"ip": str, "containers": [{"name": str, "network": str}], "error": str | None}
    """
    result = {
        "ip": ip_address,
        "containers": [],
        "error": None
    }
    
    if not await check_tool_availability(manager, "docker", target=target):
        result["error"] = "docker_not_found"
        return result
    
    # Get all containers with their IPs
    cmd = "docker ps -q | xargs -I {} docker inspect --format '{{.Name}}|{{range $net, $conf := .NetworkSettings.Networks}}{{$net}}:{{$conf.IPAddress}},{{end}}' {} 2>/dev/null"
    output = await manager.run(cmd, target=target)
    
    for line in output.strip().split("\n"):
        if "|" in line:
            name, networks = line.split("|", 1)
            name = name.lstrip("/")  # Remove leading slash
            for net_ip in networks.split(","):
                if ":" in net_ip:
                    net, ip = net_ip.split(":", 1)
                    if ip == ip_address:
                        result["containers"].append({"name": name, "network": net})
    
    if not result["containers"]:
        result["error"] = f"No container found with IP {ip_address}"
    
    return result


async def docker_networks(manager: SSHManager, target: str | None = None) -> dict[str, Any]:
    """List all Docker networks and their containers.
    
    Returns:
        {"networks": [{"name": str, "driver": str, "containers": [str]}]}
    """
    result = {"networks": [], "error": None}
    
    if not await check_tool_availability(manager, "docker", target=target):
        result["error"] = "docker_not_found"
        return result
    
    # Get networks
    cmd = "docker network ls --format '{{.Name}}|{{.Driver}}'"
    output = await manager.run(cmd, target=target)
    
    for line in output.strip().split("\n"):
        if "|" in line:
            name, driver = line.split("|", 1)
            # Get containers in this network
            inspect_cmd = f"docker network inspect {name} --format '{{{{range .Containers}}}}{{{{.Name}}}},{{{{end}}}}' 2>/dev/null"
            containers_out = await manager.run(inspect_cmd, target=target)
            containers = [c for c in containers_out.strip().split(",") if c]
            result["networks"].append({
                "name": name,
                "driver": driver,
                "containers": containers
            })
    
    return result


async def docker_cp_from_container(manager: SSHManager, container_name: str, 
                                   container_path: str, host_path: str,
                                   target: str | None = None) -> dict[str, Any]:
    """Copy file or directory from Docker container to host filesystem.
    
    Args:
        container_name: Name or ID of the container.
        container_path: Path inside the container (e.g., /tmp/backup.sql).
        host_path: Destination path on the host (e.g., /root/backups/backup.sql).
        
    Returns:
        {"success": bool, "message": str, "container": str, "container_path": str, "host_path": str}
        
    Example:
        Copy database backup from container to host:
        docker_cp_from_container("postgres-db", "/tmp/backup.sql", "/root/backups/backup.sql")
    """
    result = {
        "success": False,
        "message": "",
        "container": container_name,
        "container_path": container_path,
        "host_path": host_path
    }
    
    if not await check_tool_availability(manager, "docker", target=target):
        result["message"] = "Docker not available on target"
        return result
    
    # Ensure destination directory exists
    host_dir = "/".join(host_path.rsplit("/", 1)[:-1]) if "/" in host_path else "."
    if host_dir and host_dir != ".":
        mkdir_cmd = f"mkdir -p {host_dir}"
        await manager.run(mkdir_cmd, target=target)
    
    # Copy from container to host
    copy_cmd = f"docker cp {container_name}:{container_path} {host_path} 2>&1"
    output = await manager.run(copy_cmd, target=target)
    
    if "Error" in output or "No such" in output:
        result["message"] = f"Copy failed: {output.strip()}"
        result["success"] = False
    else:
        result["message"] = f"Successfully copied {container_path} from {container_name} to {host_path}"
        result["success"] = True
    
    return result


async def docker_cp_to_container(manager: SSHManager, host_path: str,
                                 container_name: str, container_path: str,
                                 target: str | None = None) -> dict[str, Any]:
    """Copy file or directory from host filesystem to Docker container.
    
    Args:
        host_path: Source path on the host (e.g., /root/config.yaml).
        container_name: Name or ID of the container.
        container_path: Destination path inside container (e.g., /app/config.yaml).
        
    Returns:
        {"success": bool, "message": str, "host_path": str, "container": str, "container_path": str}
        
    Example:
        Copy config file from host to container:
        docker_cp_to_container("/root/nginx.conf", "webserver", "/etc/nginx/nginx.conf")
    """
    result = {
        "success": False,
        "message": "",
        "host_path": host_path,
        "container": container_name,
        "container_path": container_path
    }
    
    if not await check_tool_availability(manager, "docker", target=target):
        result["message"] = "Docker not available on target"
        return result
    
    # Copy from host to container
    copy_cmd = f"docker cp {host_path} {container_name}:{container_path} 2>&1"
    output = await manager.run(copy_cmd, target=target)
    
    if "Error" in output or "No such" in output:
        result["message"] = f"Copy failed: {output.strip()}"
        result["success"] = False
    else:
        result["message"] = f"Successfully copied {host_path} to {container_name}:{container_path}"
        result["success"] = True
    
    return result
