"""Package Management tool.

Supports: apt (Debian/Ubuntu), apk (Alpine), dnf/yum (RHEL/Fedora).
Automatically detects the package manager on the target system.
"""
import logging
from typing import Any

from .base import detect_os

logger = logging.getLogger("ssh-mcp")


async def package_manage(
    manager,
    action: str,
    package: str,
    target: str = "primary",
) -> dict[str, Any]:
    """Manage packages on the target system.
    
    Args:
        action: "install", "remove", or "check".
        package: Name of the package.
        target: SSH connection alias.
        
    Returns:
        {"action": str, "package": str, "success": bool, "output": str, "error": str | None}
    """
    result = {
        "action": action,
        "package": package,
        "success": False,
        "output": "",
        "error": None,
    }
    
    # Validate action
    if action not in ("install", "remove", "check"):
        result["error"] = f"Invalid action: {action}. Must be 'install', 'remove', or 'check'."
        return result
    
    # Detect package manager
    os_info = await detect_os(manager, target)
    pkg_manager = os_info.get("pkg_manager")
    
    if not pkg_manager:
        result["error"] = f"Could not detect package manager. OS info: {os_info}"
        return result
    
    try:
        if action == "check":
            # Check if package is installed
            cmd = _build_check_cmd(pkg_manager, package)
            output = await manager.run(cmd, target)
            result["success"] = "installed" in output.lower() or package in output
            result["output"] = output.strip()
        elif action == "install":
            cmd = _build_install_cmd(pkg_manager, package)
            output = await manager.run(cmd, target)
            result["output"] = output.strip()
            # Check for success indicators
            result["success"] = "error" not in output.lower() and "failed" not in output.lower()
        elif action == "remove":
            cmd = _build_remove_cmd(pkg_manager, package)
            output = await manager.run(cmd, target)
            result["output"] = output.strip()
            result["success"] = "error" not in output.lower() and "failed" not in output.lower()
    except Exception as e:
        logger.error(f"package_manage failed: {e}")
        result["error"] = str(e)
    
    return result


def _build_check_cmd(pkg_manager: str, package: str) -> str:
    """Build command to check if a package is installed."""
    if pkg_manager == "apt":
        return f"dpkg -s {package} 2>/dev/null | grep -i status || echo 'not installed'"
    elif pkg_manager == "apk":
        return f"apk info {package} 2>/dev/null || echo 'not installed'"
    elif pkg_manager in ("dnf", "yum"):
        return f"rpm -q {package} 2>/dev/null || echo 'not installed'"
    else:
        return f"echo 'unknown package manager: {pkg_manager}'"


def _build_install_cmd(pkg_manager: str, package: str) -> str:
    """Build command to install a package (non-interactive)."""
    if pkg_manager == "apt":
        return f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package} 2>&1"
    elif pkg_manager == "apk":
        return f"apk add --no-cache {package} 2>&1"
    elif pkg_manager == "dnf":
        return f"dnf install -y {package} 2>&1"
    elif pkg_manager == "yum":
        return f"yum install -y {package} 2>&1"
    else:
        return f"echo 'unknown package manager: {pkg_manager}'"


def _build_remove_cmd(pkg_manager: str, package: str) -> str:
    """Build command to remove a package (non-interactive)."""
    if pkg_manager == "apt":
        return f"DEBIAN_FRONTEND=noninteractive apt-get remove -y {package} 2>&1"
    elif pkg_manager == "apk":
        return f"apk del {package} 2>&1"
    elif pkg_manager == "dnf":
        return f"dnf remove -y {package} 2>&1"
    elif pkg_manager == "yum":
        return f"yum remove -y {package} 2>&1"
    else:
        return f"echo 'unknown package manager: {pkg_manager}'"
