"""Health & Incident Diagnostic tool.

A comprehensive "one-click" SRE tool that checks multiple system health indicators.
Supports systemd and OpenRC systems.
"""
import logging
from typing import Any

from .base import detect_init_system

logger = logging.getLogger("ssh-mcp")


async def diagnose_system(
    manager,
    target: str = "primary",
) -> dict[str, Any]:
    """Perform a comprehensive system health check.
    
    Checks:
    - Load average and high resource consumers
    - OOM killer events in dmesg
    - Disk pressure (partitions over 90% full)
    - Failed services (systemd) or stopped services (OpenRC)
    
    Args:
        target: SSH connection alias.
        
    Returns:
        {
            "summary": str,
            "load": {...},
            "top_processes": [...],
            "oom_events": [...],
            "disk_pressure": [...],
            "failed_services": [...],
            "error": str | None
        }
    """
    result = {
        "summary": "",
        "load": {},
        "top_processes": [],
        "oom_events": [],
        "disk_pressure": [],
        "failed_services": [],
        "error": None,
    }
    
    issues = []
    
    try:
        # 1. Load Average
        load_output = await manager.run("cat /proc/loadavg 2>/dev/null", target)
        parts = load_output.strip().split()
        if len(parts) >= 3:
            load_1 = float(parts[0])
            load_5 = float(parts[1])
            load_15 = float(parts[2])
            result["load"] = {"1min": load_1, "5min": load_5, "15min": load_15}
            
            # Check CPU count for context
            cpu_count_output = await manager.run("nproc 2>/dev/null || echo '1'", target)
            cpu_count = int(cpu_count_output.strip()) if cpu_count_output.strip().isdigit() else 1
            
            if load_1 > cpu_count * 2:
                issues.append(f"HIGH LOAD: {load_1:.2f} (CPUs: {cpu_count})")
        
        # 2. Top Processes by CPU/Memory
        ps_output = await manager.run(
            "ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu 2>/dev/null | head -n 6",
            target
        )
        for line in ps_output.strip().split("\n")[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 5:
                result["top_processes"].append({
                    "pid": parts[0],
                    "user": parts[1],
                    "cpu": parts[2],
                    "mem": parts[3],
                    "command": parts[4],
                })
        
        # 3. OOM Killer Events
        oom_output = await manager.run(
            "dmesg 2>/dev/null | grep -i 'out of memory' | tail -n 5 || echo ''",
            target
        )
        oom_lines = [l.strip() for l in oom_output.strip().split("\n") if l.strip()]
        result["oom_events"] = oom_lines
        if oom_lines:
            issues.append(f"OOM EVENTS: {len(oom_lines)} found in dmesg")
        
        # 4. Disk Pressure
        df_output = await manager.run(
            "df -P 2>/dev/null | awk 'NR>1 {print $5, $6}' | grep -E '^[89][0-9]%|^100%'",
            target
        )
        for line in df_output.strip().split("\n"):
            if line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    result["disk_pressure"].append({
                        "usage": parts[0],
                        "mount": parts[1],
                    })
                    issues.append(f"DISK: {parts[1]} at {parts[0]}")
        
        # 5. Failed Services
        init_system = await detect_init_system(manager, target)
        if init_system == "systemd":
            svc_output = await manager.run(
                "systemctl --failed --no-legend --no-pager 2>/dev/null | head -n 10",
                target
            )
            for line in svc_output.strip().split("\n"):
                if line.strip():
                    parts = line.split()
                    if parts:
                        result["failed_services"].append(parts[0])
                        issues.append(f"FAILED SERVICE: {parts[0]}")
        elif init_system == "openrc":
            svc_output = await manager.run(
                "rc-status --crashed 2>/dev/null | head -n 10",
                target
            )
            for line in svc_output.strip().split("\n"):
                if line.strip() and "crashed" in line.lower():
                    result["failed_services"].append(line.strip())
                    issues.append(f"CRASHED SERVICE: {line.strip()}")
        
        # Build summary
        if issues:
            result["summary"] = "ISSUES FOUND:\n" + "\n".join(f"- {i}" for i in issues)
        else:
            result["summary"] = "System appears healthy. No critical issues detected."
    
    except Exception as e:
        logger.error(f"diagnose_system failed: {e}")
        result["error"] = str(e)
        result["summary"] = f"Diagnostic error: {e}"
    
    return result
