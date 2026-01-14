from __future__ import annotations

from ..ssh_manager import SSHManager

import json
from typing import Any


async def check_tool_availability(manager: SSHManager, tool: str, target: str | None = None) -> bool:
    """Checks if a command-line tool is available on the remote system."""
    check_cmd = f"command -v {tool} >/dev/null 2>&1 && echo 'present' || echo 'missing'"
    output = await manager.execute(check_cmd, target=target)
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
    return await manager.execute(cmd, target=target)

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
    return await manager.execute(cmd, target=target)


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
    output = await manager.execute(cmd, target=target)
    
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
    output = await manager.execute(cmd, target=target)
    
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
    output = await manager.execute(cmd, target=target)
    
    for line in output.strip().split("\n"):
        if "|" in line:
            name, driver = line.split("|", 1)
            # Get containers in this network
            inspect_cmd = f"docker network inspect {name} --format '{{{{range .Containers}}}}{{{{.Name}}}},{{{{end}}}}' 2>/dev/null"
            containers_out = await manager.execute(inspect_cmd, target=target)
            containers = [c for c in containers_out.strip().split(",") if c]
            result["networks"].append({
                "name": name,
                "driver": driver,
                "containers": containers
            })
    
    return result

