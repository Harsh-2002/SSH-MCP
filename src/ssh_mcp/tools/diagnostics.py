"""System diagnostics tools.

Provides scheduled task auditing and process health analysis.
"""
import logging
from typing import Any

from .base import detect_init_system, detect_os

logger = logging.getLogger("ssh-mcp")


async def list_scheduled_tasks(manager, target: str = "primary") -> dict[str, Any]:
    """Get a unified view of all scheduled tasks (cron + systemd timers).
    
    Returns:
        {
            "systemd_timers": str,
            "crontab_user": str,
            "crontab_system": str,
            "init_system": str
        }
    """
    result = {
        "init_system": "",
        "systemd_timers": "",
        "crontab_user": "",
        "crontab_system": "",
        "error": None
    }
    
    init_system = await detect_init_system(manager, target)
    result["init_system"] = init_system
    
    # Systemd timers (if available)
    if init_system == "systemd":
        timers_cmd = "systemctl list-timers --all --no-pager 2>/dev/null"
        result["systemd_timers"] = await manager.run_command(timers_cmd, target)
    
    # User crontab
    crontab_user_cmd = "crontab -l 2>/dev/null || echo 'No crontab for current user'"
    result["crontab_user"] = await manager.run_command(crontab_user_cmd, target)
    
    # System crontabs
    crontab_sys_cmd = """
echo '=== /etc/crontab ===' && cat /etc/crontab 2>/dev/null || echo 'Not found'
echo ''
echo '=== /etc/cron.d/ ===' && ls -la /etc/cron.d/ 2>/dev/null || echo 'Not found'
echo ''
echo '=== Daily jobs ===' && ls /etc/cron.daily/ 2>/dev/null || echo 'Not found'
"""
    result["crontab_system"] = await manager.run_command(crontab_sys_cmd, target)
    
    return result


async def hunt_zombies(manager, target: str = "primary") -> dict[str, Any]:
    """Find zombie (defunct) processes.
    
    Returns:
        {"count": int, "zombies": [{"pid": str, "ppid": str, "name": str}]}
    """
    result = {
        "count": 0,
        "zombies": [],
        "error": None
    }
    
    # Find zombie processes (state = Z)
    zombie_cmd = "ps aux | awk '$8 ~ /Z/ {print $2, $3, $11}'"
    output = await manager.run_command(zombie_cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            parts = line.split()
            if len(parts) >= 3:
                result["zombies"].append({
                    "pid": parts[0],
                    "ppid": parts[1] if len(parts) > 1 else "?",
                    "name": parts[2] if len(parts) > 2 else "?"
                })
    
    result["count"] = len(result["zombies"])
    
    # Also get parent info for zombies
    if result["zombies"]:
        pids = ",".join([z["pid"] for z in result["zombies"]])
        parent_cmd = f"ps -o pid,ppid,comm -p {pids} 2>/dev/null"
        parent_out = await manager.run_command(parent_cmd, target)
        result["parent_info"] = parent_out
    
    return result


async def hunt_io_hogs(manager, limit: int = 10, target: str = "primary") -> dict[str, Any]:
    """Find processes with high I/O wait or in uninterruptible sleep (D state).
    
    Returns:
        {"d_state_procs": str, "top_by_memory": str, "iotop_available": bool}
    """
    result = {
        "d_state_procs": "",
        "top_by_memory": "",
        "iotop_available": False,
        "iotop_output": "",
        "error": None
    }
    
    # Find processes in D state (uninterruptible sleep - usually waiting on I/O)
    d_state_cmd = "ps aux | awk '$8 ~ /D/ {print}' | head -20"
    result["d_state_procs"] = await manager.run_command(d_state_cmd, target)
    
    # Check if iotop is available
    iotop_check = await manager.run_command("command -v iotop >/dev/null 2>&1 && echo 'yes'", target)
    if "yes" in iotop_check:
        result["iotop_available"] = True
        # Run iotop in batch mode for one iteration
        iotop_cmd = f"iotop -b -n 1 -P 2>/dev/null | head -{limit + 2}"
        result["iotop_output"] = await manager.run_command(iotop_cmd, target)
    
    # Fallback: top processes by memory (often correlates with I/O)
    mem_cmd = f"ps aux --sort=-%mem 2>/dev/null | head -{limit + 1}"
    result["top_by_memory"] = await manager.run_command(mem_cmd, target)
    
    return result


async def check_system_health(manager, target: str = "primary") -> dict[str, Any]:
    """Quick system health overview.
    
    Returns:
        {"load": str, "memory": str, "disk_root": str, "uptime": str, "kernel": str}
    """
    result = {
        "uptime": "",
        "load_avg": "",
        "memory": {},
        "disk_root": "",
        "kernel": "",
        "error": None
    }
    
    # Uptime and load
    uptime_cmd = "uptime"
    result["uptime"] = (await manager.run_command(uptime_cmd, target)).strip()
    
    # Load average
    load_cmd = "cat /proc/loadavg 2>/dev/null"
    result["load_avg"] = (await manager.run_command(load_cmd, target)).strip()
    
    # Memory summary
    mem_cmd = "free -h 2>/dev/null | head -2"
    result["memory"] = (await manager.run_command(mem_cmd, target)).strip()
    
    # Root disk
    disk_cmd = "df -h / 2>/dev/null | tail -1"
    result["disk_root"] = (await manager.run_command(disk_cmd, target)).strip()
    
    # Kernel version
    kernel_cmd = "uname -r"
    result["kernel"] = (await manager.run_command(kernel_cmd, target)).strip()
    
    return result


async def check_oom_events(manager, lines: int = 20, target: str = "primary") -> str:
    """Check for recent Out-Of-Memory (OOM) kills in kernel logs.
    
    Returns:
        Recent OOM kill events from dmesg or journal.
    """
    # Try dmesg first
    dmesg_cmd = f"dmesg 2>/dev/null | grep -i 'oom\\|killed process\\|out of memory' | tail -{lines}"
    output = await manager.run_command(dmesg_cmd, target)
    
    if output.strip():
        return output
    
    # Fallback to journalctl
    journal_cmd = f"journalctl -k --no-pager 2>/dev/null | grep -i 'oom\\|killed process' | tail -{lines}"
    output = await manager.run_command(journal_cmd, target)
    
    if output.strip():
        return output
    
    return "No OOM events found in recent logs."
