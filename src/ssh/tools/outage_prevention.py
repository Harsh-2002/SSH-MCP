"""Outage prevention tools.

SSL cert expiry, DNS resolution, ulimits, network interface health.
"""
import logging
from typing import Any

logger = logging.getLogger("ssh-mcp")


async def check_ssl_cert(manager, host: str, port: int = 443, 
                         target: str = "primary") -> dict[str, Any]:
    """Check SSL certificate details and expiry for a host:port.
    
    Returns:
        {"host": str, "port": int, "valid": bool, "expires": str, "days_left": int, "issuer": str, "error": str | None}
    """
    result = {
        "host": host,
        "port": port,
        "valid": False,
        "expires": "",
        "days_left": -1,
        "subject": "",
        "issuer": "",
        "error": None
    }
    
    # Try openssl s_client
    cmd = f"""echo | openssl s_client -servername {host} -connect {host}:{port} 2>/dev/null | openssl x509 -noout -dates -subject -issuer 2>/dev/null"""
    output = await manager.execute(cmd, target)
    
    if "notAfter" not in output:
        result["error"] = "Could not retrieve certificate (openssl may not be installed or host unreachable)"
        return result
    
    result["valid"] = True
    
    for line in output.strip().split("\n"):
        line = line.strip()
        if line.startswith("notAfter="):
            result["expires"] = line.split("=", 1)[1]
        elif line.startswith("subject="):
            result["subject"] = line.split("=", 1)[1]
        elif line.startswith("issuer="):
            result["issuer"] = line.split("=", 1)[1]
    
    # Calculate days left
    if result["expires"]:
        days_cmd = f"""echo $(( ( $(date -d "{result['expires']}" +%s) - $(date +%s) ) / 86400 )) 2>/dev/null || echo '-1'"""
        days_out = await manager.execute(days_cmd, target)
        try:
            result["days_left"] = int(days_out.strip())
        except:
            result["days_left"] = -1
    
    return result


async def check_dns(manager, hostname: str, target: str = "primary") -> dict[str, Any]:
    """Check if a hostname resolves correctly from the target.
    
    Returns:
        {"hostname": str, "resolves": bool, "ips": [str], "error": str | None}
    """
    result = {
        "hostname": hostname,
        "resolves": False,
        "ips": [],
        "error": None
    }
    
    # Try dig first, then nslookup, then getent
    cmd = f"""dig +short {hostname} 2>/dev/null || nslookup {hostname} 2>/dev/null | grep 'Address:' | tail -n +2 | awk '{{print $2}}' || getent hosts {hostname} 2>/dev/null | awk '{{print $1}}'"""
    output = await manager.execute(cmd, target)
    
    ips = [line.strip() for line in output.strip().split("\n") if line.strip() and not line.startswith(";")]
    
    if ips:
        result["resolves"] = True
        result["ips"] = ips
    else:
        result["error"] = f"Could not resolve {hostname}"
    
    return result


async def check_ulimits(manager, target: str = "primary") -> dict[str, Any]:
    """Check resource limits (open files, max processes, etc).
    
    Returns:
        {"limits": dict, "warnings": [str]}
    """
    result = {
        "limits": {},
        "current_usage": {},
        "warnings": [],
        "error": None
    }
    
    # Get limits
    limits_cmd = "ulimit -a 2>/dev/null"
    limits_out = await manager.execute(limits_cmd, target)
    
    for line in limits_out.strip().split("\n"):
        if "open files" in line.lower():
            parts = line.split()
            try:
                result["limits"]["open_files"] = int(parts[-1])
            except:
                result["limits"]["open_files"] = parts[-1]
        elif "max user processes" in line.lower():
            parts = line.split()
            try:
                result["limits"]["max_processes"] = int(parts[-1])
            except:
                result["limits"]["max_processes"] = parts[-1]
    
    # Get current open files count
    fd_cmd = "cat /proc/sys/fs/file-nr 2>/dev/null"
    fd_out = await manager.execute(fd_cmd, target)
    if fd_out.strip():
        parts = fd_out.strip().split()
        if len(parts) >= 3:
            result["current_usage"]["open_files"] = int(parts[0])
            result["current_usage"]["max_files"] = int(parts[2])
            # Warn if over 80% used
            if result["current_usage"]["open_files"] > 0.8 * result["current_usage"]["max_files"]:
                result["warnings"].append(f"System-wide file descriptors at {result['current_usage']['open_files']}/{result['current_usage']['max_files']} (>80%)")
    
    # Get current process count
    proc_cmd = "ps aux | wc -l"
    proc_out = await manager.execute(proc_cmd, target)
    try:
        result["current_usage"]["processes"] = int(proc_out.strip()) - 1  # minus header
    except:
        pass
    
    return result


async def check_network_errors(manager, target: str = "primary") -> dict[str, Any]:
    """Check for network interface errors, drops, and issues.
    
    Returns:
        {"interfaces": [{"name": str, "rx_errors": int, "tx_errors": int, "rx_dropped": int, ...}], "warnings": [str]}
    """
    result = {
        "interfaces": [],
        "warnings": [],
        "error": None
    }
    
    # Parse /proc/net/dev for statistics
    cmd = "cat /proc/net/dev 2>/dev/null"
    output = await manager.execute(cmd, target)
    
    lines = output.strip().split("\n")
    for line in lines[2:]:  # Skip headers
        if ":" not in line:
            continue
        parts = line.split(":")
        iface = parts[0].strip()
        stats = parts[1].split()
        
        if len(stats) >= 12:
            iface_stats = {
                "name": iface,
                "rx_bytes": int(stats[0]),
                "rx_packets": int(stats[1]),
                "rx_errors": int(stats[2]),
                "rx_dropped": int(stats[3]),
                "tx_bytes": int(stats[8]),
                "tx_packets": int(stats[9]),
                "tx_errors": int(stats[10]),
                "tx_dropped": int(stats[11])
            }
            result["interfaces"].append(iface_stats)
            
            # Generate warnings for issues
            if iface_stats["rx_errors"] > 0:
                result["warnings"].append(f"{iface}: {iface_stats['rx_errors']} RX errors")
            if iface_stats["tx_errors"] > 0:
                result["warnings"].append(f"{iface}: {iface_stats['tx_errors']} TX errors")
            if iface_stats["rx_dropped"] > 100:
                result["warnings"].append(f"{iface}: {iface_stats['rx_dropped']} RX dropped packets")
            if iface_stats["tx_dropped"] > 100:
                result["warnings"].append(f"{iface}: {iface_stats['tx_dropped']} TX dropped packets")
    
    return result
