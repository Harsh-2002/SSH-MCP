from __future__ import annotations

from ..ssh_manager import SSHManager

from typing import Any


def _parse_meminfo_kb(meminfo: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in meminfo.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        rest = rest.strip()
        if not rest:
            continue
        parts = rest.split()
        try:
            out[key] = int(parts[0])
        except ValueError:
            continue
    return out


def _parse_df_bytes(df_line: str) -> dict[str, Any]:
    # df -P -B1 / output line: Filesystem 1024-blocks Used Available Capacity Mounted on
    parts = df_line.split()
    if len(parts) < 6:
        return {"raw": df_line}
    filesystem, total, used, avail, capacity, mount = parts[:6]
    return {
        "filesystem": filesystem,
        "total_bytes": int(total),
        "used_bytes": int(used),
        "available_bytes": int(avail),
        "used_percent": int(capacity.strip("%")) if capacity.endswith("%") else None,
        "mount": mount,
    }


async def usage(manager: SSHManager, target: str | None = None) -> dict[str, Any]:
    """Structured system snapshot (load, memory, disk)."""

    load_res = await manager.run_result("cat /proc/loadavg", target=target)
    mem_res = await manager.run_result("cat /proc/meminfo", target=target)
    disk_res = await manager.run_result("df -P -B1 / | tail -n 1", target=target)

    load_parts = load_res["stdout"].strip().split()
    load_1 = float(load_parts[0]) if len(load_parts) > 0 else None
    load_5 = float(load_parts[1]) if len(load_parts) > 1 else None
    load_15 = float(load_parts[2]) if len(load_parts) > 2 else None

    mem_kb = _parse_meminfo_kb(mem_res["stdout"])
    mem_total_kb = mem_kb.get("MemTotal")
    mem_avail_kb = mem_kb.get("MemAvailable")

    memory: dict[str, Any] = {
        "mem_total_bytes": mem_total_kb * 1024 if mem_total_kb is not None else None,
        "mem_available_bytes": mem_avail_kb * 1024 if mem_avail_kb is not None else None,
    }

    if mem_total_kb is not None and mem_avail_kb is not None and mem_total_kb > 0:
        used_kb = mem_total_kb - mem_avail_kb
        memory["mem_used_bytes"] = used_kb * 1024
        memory["mem_used_percent"] = round((used_kb / mem_total_kb) * 100, 2)

    disk = _parse_df_bytes(disk_res["stdout"].strip())

    return {
        "target": load_res["target"],
        "loadavg": {"1": load_1, "5": load_5, "15": load_15},
        "memory": memory,
        "disk": disk,
    }

async def logs(manager: SSHManager, path: str, lines: int = 50, grep: str | None = None, target: str | None = None) -> str:
    """
    Safely read the end of a log file.
    Args:
        lines: Number of lines to read (max 500).
        grep: Optional string to filter lines.
    """
    # Safety limit
    if lines > 500: lines = 500
    
    cmd = f"tail -n {lines} {path}"
    if grep:
        # Simple grep filtering
        cmd += f" | grep '{grep}'"
        
    return await manager.execute(cmd, target=target)

async def ps(manager: SSHManager, sort_by: str = "cpu", limit: int = 10, target: str | None = None) -> str:
    """
    List top processes.
    Args:
        sort_by: 'cpu' or 'mem'
        limit: Number of processes to show.
    """
    sort_flag = "-%cpu" if sort_by == "cpu" else "-%mem"
    
    # ps options:
    # -e: all processes
    # -o: output format
    # --sort: sorting order
    cmd = f"ps -eo pid,user,%cpu,%mem,comm --sort={sort_flag} | head -n {limit + 1}"
    
    return await manager.execute(cmd, target=target)
