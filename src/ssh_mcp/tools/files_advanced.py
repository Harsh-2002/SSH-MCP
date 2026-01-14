"""Advanced file system tools.

Provides disk usage analysis and large file discovery.
"""
import logging
from typing import Any

logger = logging.getLogger("ssh-mcp")


async def find_large_files(manager, path: str = "/", limit: int = 10,
                           min_size: str | None = None,
                           target: str = "primary") -> dict[str, Any]:
    """Find the largest files recursively under a path.
    
    Args:
        path: Directory to search.
        limit: Number of results to return.
        min_size: Optional minimum size filter (e.g., "100M", "1G").
        
    Returns:
        {"path": str, "files": [{"size": str, "path": str}], "error": str | None}
    """
    result = {
        "search_path": path,
        "files": [],
        "error": None
    }
    
    # Build the find command
    size_filter = f"-size +{min_size}" if min_size else ""
    cmd = f"find {path} -type f {size_filter} -exec du -h {{}} + 2>/dev/null | sort -rh | head -n {limit}"
    
    output = await manager.run_command(cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                result["files"].append({
                    "size": parts[0],
                    "path": parts[1]
                })
    
    if not result["files"]:
        result["error"] = f"No files found or permission denied in {path}"
    
    return result


async def find_large_folders(manager, path: str = "/", limit: int = 10,
                             max_depth: int = 2,
                             target: str = "primary") -> dict[str, Any]:
    """Find the largest folders under a path.
    
    Args:
        path: Directory to analyze.
        limit: Number of results to return.
        max_depth: How deep to analyze (1 = immediate children only).
        
    Returns:
        {"path": str, "folders": [{"size": str, "path": str}], "error": str | None}
    """
    result = {
        "search_path": path,
        "folders": [],
        "error": None
    }
    
    cmd = f"du -h -d {max_depth} {path} 2>/dev/null | sort -rh | head -n {limit}"
    output = await manager.run_command(cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                result["folders"].append({
                    "size": parts[0],
                    "path": parts[1]
                })
    
    if not result["folders"]:
        result["error"] = f"No folders found or permission denied in {path}"
    
    return result


async def disk_usage_summary(manager, target: str = "primary") -> dict[str, Any]:
    """Get overall disk usage for all mounted filesystems.
    
    Returns:
        {"filesystems": [{"device": str, "size": str, "used": str, "avail": str, "use_pct": str, "mount": str}]}
    """
    result = {
        "filesystems": [],
        "error": None
    }
    
    cmd = "df -h 2>/dev/null | grep -v 'tmpfs\\|overlay' | tail -n +2"
    output = await manager.run_command(cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            parts = line.split()
            if len(parts) >= 6:
                result["filesystems"].append({
                    "device": parts[0],
                    "size": parts[1],
                    "used": parts[2],
                    "avail": parts[3],
                    "use_pct": parts[4],
                    "mount": parts[5]
                })
    
    return result


async def find_old_files(manager, path: str, days: int = 30, limit: int = 20,
                         target: str = "primary") -> dict[str, Any]:
    """Find files older than N days.
    
    Useful for identifying stale logs, temp files, or forgotten backups.
    
    Args:
        path: Directory to search.
        days: Minimum age in days.
        limit: Maximum results.
        
    Returns:
        {"path": str, "files": [{"mtime": str, "size": str, "path": str}]}
    """
    result = {
        "search_path": path,
        "min_age_days": days,
        "files": [],
        "error": None
    }
    
    cmd = f"find {path} -type f -mtime +{days} -exec ls -lh {{}} \\; 2>/dev/null | head -{limit}"
    output = await manager.run_command(cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            parts = line.split()
            if len(parts) >= 9:
                result["files"].append({
                    "size": parts[4],
                    "mtime": f"{parts[5]} {parts[6]} {parts[7]}",
                    "path": parts[8] if len(parts) == 9 else " ".join(parts[8:])
                })
    
    return result


async def find_recently_modified(manager, path: str, minutes: int = 60, limit: int = 20,
                                  target: str = "primary") -> dict[str, Any]:
    """Find files modified within the last N minutes.
    
    Useful for tracking what changed during an incident.
    
    Args:
        path: Directory to search.
        minutes: Time window.
        limit: Maximum results.
        
    Returns:
        {"path": str, "files": [str]}
    """
    result = {
        "search_path": path,
        "time_window_minutes": minutes,
        "files": [],
        "error": None
    }
    
    cmd = f"find {path} -type f -mmin -{minutes} 2>/dev/null | head -{limit}"
    output = await manager.run_command(cmd, target)
    
    for line in output.strip().split("\n"):
        if line.strip():
            result["files"].append(line.strip())
    
    return result
