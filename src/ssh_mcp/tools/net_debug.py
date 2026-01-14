"""Network debugging and connectivity probing tools.

Tests if target machine can reach specific hosts and ports.
"""
import logging
from typing import Any

logger = logging.getLogger("ssh-mcp")


async def test_connection(manager, host: str, port: int, timeout: int = 2, 
                          target: str = "primary") -> dict[str, Any]:
    """Test TCP connectivity from target to a specific host:port.
    
    Tries multiple methods in order of preference:
    1. nc (netcat)
    2. bash /dev/tcp redirect
    3. Python socket
    
    Args:
        host: Destination hostname or IP.
        port: Destination port number.
        timeout: Connection timeout in seconds.
        
    Returns:
        {"host": str, "port": int, "reachable": bool, "method": str, "error": str | None}
    """
    result = {
        "host": host,
        "port": port,
        "reachable": False,
        "method": "",
        "latency_ms": None,
        "error": None
    }
    
    # Method 1: nc (netcat) - most common
    nc_cmd = f"nc -zv -w {timeout} {host} {port} 2>&1"
    nc_out = await manager.execute(nc_cmd, target)
    if "succeeded" in nc_out.lower() or "connected" in nc_out.lower() or "open" in nc_out.lower():
        result["reachable"] = True
        result["method"] = "nc"
        return result
    
    # Method 2: bash /dev/tcp (works on most bash shells)
    bash_cmd = f"timeout {timeout} bash -c 'echo > /dev/tcp/{host}/{port}' 2>&1 && echo 'OK' || echo 'FAIL'"
    bash_out = await manager.execute(bash_cmd, target)
    if "OK" in bash_out:
        result["reachable"] = True
        result["method"] = "bash"
        return result
    
    # Method 3: Python socket (universal fallback)
    py_cmd = f"""python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout({timeout})
try:
    s.connect(('{host}', {port}))
    print('OK')
except Exception as e:
    print('FAIL:', e)
finally:
    s.close()
" 2>&1"""
    py_out = await manager.execute(py_cmd, target)
    if "OK" in py_out:
        result["reachable"] = True
        result["method"] = "python"
        return result
    
    # All methods failed
    result["error"] = f"Connection failed. Last output: {py_out.strip()}"
    return result


async def check_port_owner(manager, port: int, target: str = "primary") -> dict[str, Any]:
    """Find which process/container is listening on a specific port.
    
    Tries:
    1. ss (modern Linux)
    2. netstat (legacy)
    3. lsof (if available)
    
    Returns:
        {"port": int, "listening": bool, "process": str | None, "pid": str | None, "error": str | None}
    """
    result = {
        "port": port,
        "listening": False,
        "process": None,
        "pid": None,
        "user": None,
        "error": None
    }
    
    # Try ss first (modern)
    ss_cmd = f"ss -tlnp 'sport = :{port}' 2>/dev/null | grep -v 'State'"
    ss_out = await manager.execute(ss_cmd, target)
    if ss_out.strip():
        result["listening"] = True
        result["process"] = ss_out.strip()
        # Extract PID if present
        if "pid=" in ss_out:
            import re
            match = re.search(r'pid=(\d+)', ss_out)
            if match:
                result["pid"] = match.group(1)
        return result
    
    # Try netstat
    netstat_cmd = f"netstat -tlnp 2>/dev/null | grep ':{port} '"
    netstat_out = await manager.execute(netstat_cmd, target)
    if netstat_out.strip():
        result["listening"] = True
        result["process"] = netstat_out.strip()
        return result
    
    # Try lsof
    lsof_cmd = f"lsof -i :{port} -P -n 2>/dev/null | head -5"
    lsof_out = await manager.execute(lsof_cmd, target)
    if lsof_out.strip() and "COMMAND" in lsof_out:
        result["listening"] = True
        result["process"] = lsof_out.strip()
        return result
    
    result["error"] = f"No process listening on port {port}"
    return result


async def scan_ports(manager, host: str, ports: list[int], timeout: int = 1,
                     target: str = "primary") -> dict[str, Any]:
    """Quick scan multiple ports on a host.
    
    Returns:
        {"host": str, "open_ports": [int], "closed_ports": [int]}
    """
    result = {
        "host": host,
        "open_ports": [],
        "closed_ports": []
    }
    
    for port in ports:
        conn = await test_connection(manager, host, port, timeout, target)
        if conn["reachable"]:
            result["open_ports"].append(port)
        else:
            result["closed_ports"].append(port)
    
    return result
