"""Base helpers for OS/environment detection."""
import logging

logger = logging.getLogger("ssh-mcp")


async def detect_os(manager, target: str) -> dict:
    """Detect the OS family and package manager of target.
    
    Returns:
        {"os": "debian"|"alpine"|"rhel"|"unknown", "pkg_manager": "apt"|"apk"|"dnf"|"yum"|None}
    """
    # Check /etc/os-release
    result = await manager.run("cat /etc/os-release 2>/dev/null || echo ''", target)
    text = result.lower()
    
    if "alpine" in text:
        return {"os": "alpine", "pkg_manager": "apk"}
    elif "debian" in text or "ubuntu" in text:
        return {"os": "debian", "pkg_manager": "apt"}
    elif "fedora" in text or "rhel" in text or "centos" in text or "rocky" in text or "almalinux" in text:
        # Check if dnf or yum
        dnf_check = await manager.run("command -v dnf >/dev/null 2>&1 && echo 'dnf' || echo ''", target)
        pkg = "dnf" if "dnf" in dnf_check else "yum"
        return {"os": "rhel", "pkg_manager": pkg}
    else:
        return {"os": "unknown", "pkg_manager": None}


async def detect_init_system(manager, target: str) -> str:
    """Detect init system: systemd, openrc, or unknown."""
    # Check for systemd
    systemd_check = await manager.run(
        "command -v systemctl >/dev/null 2>&1 && systemctl --version >/dev/null 2>&1 && echo 'systemd'",
        target
    )
    if "systemd" in systemd_check:
        return "systemd"
    
    # Check for OpenRC (Alpine)
    openrc_check = await manager.run(
        "command -v rc-status >/dev/null 2>&1 && echo 'openrc'",
        target
    )
    if "openrc" in openrc_check:
        return "openrc"
    
    return "unknown"


async def is_docker_container(manager, name: str, target: str) -> bool:
    """Check if a name corresponds to a running Docker container."""
    result = await manager.run(
        f"docker ps --filter 'name=^{name}$' --format '{{{{.Names}}}}' 2>/dev/null || echo ''",
        target
    )
    return name in result.strip()


async def docker_available(manager, target: str) -> bool:
    """Check if docker CLI is available on target."""
    result = await manager.run(
        "command -v docker >/dev/null 2>&1 && echo 'yes' || echo 'no'",
        target
    )
    return "yes" in result
