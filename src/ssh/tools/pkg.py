"""Universal package manager tools.

Supports: APT (Debian/Ubuntu), APK (Alpine), DNF/YUM (RHEL/Fedora/CentOS).
"""
import logging
from typing import Any

from .base import detect_os

logger = logging.getLogger("ssh-mcp")


async def install_package(manager, packages: list[str], target: str = "primary") -> dict[str, Any]:
    """Install one or more packages using the system's package manager.
    
    Args:
        packages: List of package names to install.
        
    Returns:
        {"os": str, "pkg_manager": str, "packages": list, "output": str, "error": str | None}
    """
    result = {
        "os": "",
        "pkg_manager": "",
        "packages": packages,
        "output": "",
        "error": None
    }
    
    os_info = await detect_os(manager, target)
    result["os"] = os_info["os"]
    result["pkg_manager"] = os_info["pkg_manager"]
    
    pkg_list = " ".join(packages)
    
    if os_info["pkg_manager"] == "apt":
        cmd = f"DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "apk":
        cmd = f"apk update && apk add --no-cache {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "dnf":
        cmd = f"dnf install -y {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "yum":
        cmd = f"yum install -y {pkg_list} 2>&1"
    else:
        result["error"] = f"Unknown package manager for OS: {os_info['os']}"
        return result
    
    try:
        result["output"] = await manager.execute(cmd, target)
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def remove_package(manager, packages: list[str], target: str = "primary") -> dict[str, Any]:
    """Remove one or more packages using the system's package manager.
    
    Args:
        packages: List of package names to remove.
        
    Returns:
        {"os": str, "pkg_manager": str, "packages": list, "output": str, "error": str | None}
    """
    result = {
        "os": "",
        "pkg_manager": "",
        "packages": packages,
        "output": "",
        "error": None
    }
    
    os_info = await detect_os(manager, target)
    result["os"] = os_info["os"]
    result["pkg_manager"] = os_info["pkg_manager"]
    
    pkg_list = " ".join(packages)
    
    if os_info["pkg_manager"] == "apt":
        cmd = f"apt-get remove -y {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "apk":
        cmd = f"apk del {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "dnf":
        cmd = f"dnf remove -y {pkg_list} 2>&1"
    elif os_info["pkg_manager"] == "yum":
        cmd = f"yum remove -y {pkg_list} 2>&1"
    else:
        result["error"] = f"Unknown package manager for OS: {os_info['os']}"
        return result
    
    try:
        result["output"] = await manager.execute(cmd, target)
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def search_package(manager, query: str, target: str = "primary") -> dict[str, Any]:
    """Search for packages matching a query.
    
    Args:
        query: Search term.
        
    Returns:
        {"os": str, "pkg_manager": str, "query": str, "results": str, "error": str | None}
    """
    result = {
        "os": "",
        "pkg_manager": "",
        "query": query,
        "results": "",
        "error": None
    }
    
    os_info = await detect_os(manager, target)
    result["os"] = os_info["os"]
    result["pkg_manager"] = os_info["pkg_manager"]
    
    if os_info["pkg_manager"] == "apt":
        cmd = f"apt-cache search {query} 2>&1 | head -20"
    elif os_info["pkg_manager"] == "apk":
        cmd = f"apk search {query} 2>&1 | head -20"
    elif os_info["pkg_manager"] == "dnf":
        cmd = f"dnf search {query} 2>&1 | head -30"
    elif os_info["pkg_manager"] == "yum":
        cmd = f"yum search {query} 2>&1 | head -30"
    else:
        result["error"] = f"Unknown package manager for OS: {os_info['os']}"
        return result
    
    try:
        result["results"] = await manager.execute(cmd, target)
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def list_installed(manager, grep: str | None = None, target: str = "primary") -> dict[str, Any]:
    """List installed packages, optionally filtering by name.
    
    Args:
        grep: Optional filter string.
        
    Returns:
        {"os": str, "pkg_manager": str, "packages": str, "error": str | None}
    """
    result = {
        "os": "",
        "pkg_manager": "",
        "packages": "",
        "error": None
    }
    
    os_info = await detect_os(manager, target)
    result["os"] = os_info["os"]
    result["pkg_manager"] = os_info["pkg_manager"]
    
    grep_suffix = f" | grep -i {grep}" if grep else " | head -50"
    
    if os_info["pkg_manager"] == "apt":
        cmd = f"dpkg --get-selections{grep_suffix} 2>&1"
    elif os_info["pkg_manager"] == "apk":
        cmd = f"apk list --installed{grep_suffix} 2>&1"
    elif os_info["pkg_manager"] in ("dnf", "yum"):
        cmd = f"rpm -qa{grep_suffix} 2>&1"
    else:
        result["error"] = f"Unknown package manager for OS: {os_info['os']}"
        return result
    
    try:
        result["packages"] = await manager.execute(cmd, target)
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def check_package(manager, package: str, target: str = "primary") -> dict[str, Any]:
    """Check if a specific package is installed.
    
    Returns:
        {"package": str, "installed": bool, "version": str | None, "error": str | None}
    """
    result = {
        "package": package,
        "installed": False,
        "version": None,
        "error": None
    }
    
    os_info = await detect_os(manager, target)
    
    try:
        if os_info["pkg_manager"] == "apt":
            cmd = f"dpkg -s {package} 2>/dev/null | grep -E '^(Status|Version):'"
            output = await manager.execute(cmd, target)
            if "install ok installed" in output.lower():
                result["installed"] = True
                for line in output.split("\n"):
                    if line.startswith("Version:"):
                        result["version"] = line.split(":", 1)[1].strip()
                        
        elif os_info["pkg_manager"] == "apk":
            cmd = f"apk info -v {package} 2>/dev/null"
            output = await manager.execute(cmd, target)
            if output.strip():
                result["installed"] = True
                result["version"] = output.strip().replace(package + "-", "")
                
        elif os_info["pkg_manager"] in ("dnf", "yum"):
            cmd = f"rpm -q {package} 2>/dev/null"
            output = await manager.execute(cmd, target)
            if "not installed" not in output.lower() and output.strip():
                result["installed"] = True
                result["version"] = output.strip().replace(package + "-", "")
                
    except Exception as e:
        result["error"] = str(e)
    
    return result
