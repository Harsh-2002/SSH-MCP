"""Journal & Log Analysis tool.

Supports systemd (journalctl) and OpenRC/traditional syslog fallback.
Automatically detects the init system on the target.
"""
import logging
from typing import Any

from .base import detect_init_system

logger = logging.getLogger("ssh-mcp")


async def journal_read(
    manager,
    service: str | None = None,
    since: str | None = None,
    lines: int = 100,
    priority: str | None = None,
    target: str = "primary",
) -> dict[str, Any]:
    """Read system logs or service-specific logs.
    
    Args:
        service: Service name to filter logs (e.g., "nginx", "sshd").
        since: Time filter (e.g., "1 hour ago", "2025-01-15 10:00:00").
        lines: Number of lines to return (default: 100, max: 500).
        priority: Log priority filter for systemd: "emerg", "alert", "crit", "err", "warning", "notice", "info", "debug".
        target: SSH connection alias.
        
    Returns:
        {"logs": str, "source": str, "error": str | None}
    """
    result = {"logs": "", "source": "", "error": None}
    
    # Limit lines
    if lines > 500:
        lines = 500
    
    init_system = await detect_init_system(manager, target)
    
    try:
        if init_system == "systemd":
            cmd = _build_journalctl_cmd(service, since, lines, priority)
            result["source"] = "journalctl"
        else:
            # Fallback to traditional log files
            cmd = _build_syslog_cmd(service, lines)
            result["source"] = "syslog"
        
        output = await manager.run(cmd, target)
        result["logs"] = output.strip()
    except Exception as e:
        logger.error(f"journal_read failed: {e}")
        result["error"] = str(e)
    
    return result


def _build_journalctl_cmd(
    service: str | None,
    since: str | None,
    lines: int,
    priority: str | None
) -> str:
    """Build journalctl command."""
    cmd_parts = ["journalctl", "--no-pager"]
    
    if service:
        cmd_parts.extend(["-u", service])
    
    if since:
        cmd_parts.extend(["--since", f"'{since}'"])
    
    if priority:
        cmd_parts.extend(["-p", priority])
    
    cmd_parts.extend(["-n", str(lines)])
    cmd_parts.append("2>/dev/null")
    
    return " ".join(cmd_parts)


def _build_syslog_cmd(service: str | None, lines: int) -> str:
    """Build syslog fallback command for non-systemd systems."""
    # Try common log locations
    log_files = [
        "/var/log/syslog",
        "/var/log/messages",
        "/var/log/daemon.log",
    ]
    
    # Build a command that tries each log file
    if service:
        # Filter by service name
        cmd = f"cat {' '.join(log_files)} 2>/dev/null | grep -i '{service}' | tail -n {lines}"
    else:
        cmd = f"cat {' '.join(log_files)} 2>/dev/null | tail -n {lines}"
    
    return cmd


async def dmesg_read(
    manager,
    grep: str | None = None,
    lines: int = 100,
    target: str = "primary",
) -> dict[str, Any]:
    """Read kernel ring buffer (dmesg).
    
    Args:
        grep: Optional pattern to filter messages.
        lines: Number of lines to return (default: 100).
        target: SSH connection alias.
        
    Returns:
        {"logs": str, "error": str | None}
    """
    result = {"logs": "", "error": None}
    
    if lines > 500:
        lines = 500
    
    try:
        cmd = "dmesg --time-format iso 2>/dev/null || dmesg 2>/dev/null"
        if grep:
            cmd += f" | grep -i '{grep}'"
        cmd += f" | tail -n {lines}"
        
        output = await manager.run(cmd, target)
        result["logs"] = output.strip()
    except Exception as e:
        logger.error(f"dmesg_read failed: {e}")
        result["error"] = str(e)
    
    return result
