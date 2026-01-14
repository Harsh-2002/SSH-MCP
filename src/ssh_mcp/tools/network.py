from __future__ import annotations

from ..ssh_manager import SSHManager

from typing import Any


def _split_host_port(value: str) -> tuple[str, int | None]:
    value = value.strip()
    if not value:
        return "", None

    # IPv6 format: [addr]:port
    if value.startswith("[") and "]:" in value:
        host = value[1 : value.rfind("]")]
        port_part = value.rsplit(":", 1)[-1]
        if port_part in ("*", ""):
            return host, None
        try:
            return host, int(port_part)
        except ValueError:
            return host, None

    if ":" in value:
        host, port_part = value.rsplit(":", 1)
        if port_part in ("*", ""):
            return host, None
        try:
            return host, int(port_part)
        except ValueError:
            return host, None

    return value, None


async def check_tool_availability(manager: SSHManager, tool: str, target: str | None = None) -> bool:
    """Checks if a command-line tool is available on the remote system."""
    check_cmd = f"command -v {tool} >/dev/null 2>&1 && echo 'present' || echo 'missing'"
    output = await manager.execute(check_cmd, target=target)
    return "present" in output


async def net_stat(manager: SSHManager, port: int | None = None, target: str | None = None) -> dict[str, Any]:
    """List listening sockets as structured data."""

    # Prefer ss
    if await check_tool_availability(manager, "ss", target=target):
        res = await manager.run_result("ss -H -ltunp", target=target)
        entries: list[dict[str, Any]] = []
        for line in res["stdout"].splitlines():
            cols = line.split()
            if len(cols) < 6:
                continue
            netid, state, recvq, sendq, local, peer = cols[:6]
            process = " ".join(cols[6:]) if len(cols) > 6 else ""
            local_host, local_port = _split_host_port(local)
            peer_host, peer_port = _split_host_port(peer)

            if port is not None and local_port != port:
                continue

            entries.append(
                {
                    "proto": netid,
                    "state": state,
                    "recv_q": recvq,
                    "send_q": sendq,
                    "local": {"host": local_host, "port": local_port},
                    "peer": {"host": peer_host, "port": peer_port},
                    "process": process,
                }
            )

        return {"target": res["target"], "tool": "ss", "port": port, "entries": entries}

    # Fallback netstat
    if await check_tool_availability(manager, "netstat", target=target):
        res = await manager.run_result("netstat -lntup 2>/dev/null || netstat -lntu", target=target)
        entries: list[dict[str, Any]] = []
        for line in res["stdout"].splitlines():
            line = line.strip()
            if not line or line.lower().startswith("proto") or line.lower().startswith("active"):
                continue
            cols = line.split()
            if len(cols) < 4:
                continue

            proto = cols[0]
            local = cols[3] if len(cols) > 3 else ""
            foreign = cols[4] if len(cols) > 4 else ""
            state = cols[5] if len(cols) > 5 and proto.startswith("tcp") else ""
            pidprog = cols[6] if len(cols) > 6 else ""

            local_host, local_port = _split_host_port(local)
            foreign_host, foreign_port = _split_host_port(foreign)

            if port is not None and local_port != port:
                continue

            entries.append(
                {
                    "proto": proto,
                    "state": state,
                    "local": {"host": local_host, "port": local_port},
                    "peer": {"host": foreign_host, "port": foreign_port},
                    "process": pidprog,
                }
            )

        return {"target": res["target"], "tool": "netstat", "port": port, "entries": entries}

    return {"target": target, "error": "no_ss_or_netstat"}

async def net_dump(manager: SSHManager, interface: str = "any", count: int = 20, filter: str = "", target: str | None = None) -> str:
    """
    Safely captures network traffic using tcpdump with strict limits.
    """
    if not await check_tool_availability(manager, "tcpdump", target=target):
        return "Error: tcpdump is not installed."

    # Safety parameters:
    # timeout 10s: Hard system timeout prevents hanging
    # -c {count}: Exit after receiving count packets
    # -n: Don't convert addresses to names (avoids DNS lookups)
    
    cmd = f"timeout 10s sudo tcpdump -i {interface} -c {count} -n {filter}"
    
    output = await manager.execute(cmd, target=target)
    
    # Handle sudo issues gracefully
    if "sudo: a terminal is required" in output or "sudo: no tty" in output:
         return "Error: sudo requires a password or TTY. Ensure the user has passwordless sudo for tcpdump."
         
    return output

async def curl(manager: SSHManager, url: str, method: str = "GET", target: str | None = None) -> str:
    """Check connectivity to a URL."""
    if not await check_tool_availability(manager, "curl", target=target):
        return "Error: curl is not installed."
        
    # -I: Head only (if GET/HEAD) to be faster, unless we want body.
    # But usually 'curl' implies full check. We'll use -v for debug info.
    # -m 5: 5 second timeout
    cmd = f"curl -X {method} -m 5 -v {url}"
    return await manager.execute(cmd, target=target)
