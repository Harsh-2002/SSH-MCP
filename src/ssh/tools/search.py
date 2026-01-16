"""Unified Search tool for files and text patterns.

Uses POSIX-compliant find and grep commands.
"""
import logging
from typing import Any

logger = logging.getLogger("ssh-mcp")


async def search_files(
    manager,
    pattern: str,
    path: str = "/",
    max_depth: int | None = 5,
    file_type: str | None = None,
    target: str = "primary",
) -> dict[str, Any]:
    """Search for files by name pattern.
    
    Args:
        pattern: Glob pattern for file names (e.g., "*.log", "config*").
        path: Starting directory for search.
        max_depth: Maximum directory depth to search (default: 5, None for unlimited).
        file_type: Optional filter: "f" for files, "d" for directories.
        target: SSH connection alias.
        
    Returns:
        {"files": [...], "count": int, "error": str | None}
    """
    result = {"files": [], "count": 0, "error": None, "path": path, "pattern": pattern}
    
    # Build find command
    cmd_parts = ["find", path]
    
    if max_depth is not None:
        cmd_parts.extend(["-maxdepth", str(max_depth)])
    
    if file_type:
        cmd_parts.extend(["-type", file_type])
    
    cmd_parts.extend(["-name", f"'{pattern}'"])
    cmd_parts.append("2>/dev/null | head -n 100")  # Limit results
    
    cmd = " ".join(cmd_parts)
    
    try:
        output = await manager.run(cmd, target)
        files = [f.strip() for f in output.strip().split("\n") if f.strip()]
        result["files"] = files
        result["count"] = len(files)
    except Exception as e:
        logger.error(f"search_files failed: {e}")
        result["error"] = str(e)
    
    return result


async def search_text(
    manager,
    pattern: str,
    path: str,
    recursive: bool = True,
    ignore_case: bool = False,
    max_results: int = 50,
    target: str = "primary",
) -> dict[str, Any]:
    """Search for text patterns inside files.
    
    Args:
        pattern: Regex pattern to search for.
        path: File or directory to search in.
        recursive: Search recursively in subdirectories.
        ignore_case: Case-insensitive search.
        max_results: Maximum number of matching lines to return (default: 50).
        target: SSH connection alias.
        
    Returns:
        {"matches": [{"file": str, "line": int, "text": str}], "count": int, "error": str | None}
    """
    result = {"matches": [], "count": 0, "error": None, "pattern": pattern, "path": path}
    
    # Build grep command
    cmd_parts = ["grep", "-n"]  # -n for line numbers
    
    if recursive:
        cmd_parts.append("-r")
    
    if ignore_case:
        cmd_parts.append("-i")
    
    # Extended regex for more powerful patterns
    cmd_parts.append("-E")
    
    cmd_parts.append(f"'{pattern}'")
    cmd_parts.append(path)
    cmd_parts.append(f"2>/dev/null | head -n {max_results}")
    
    cmd = " ".join(cmd_parts)
    
    try:
        output = await manager.run(cmd, target)
        matches = []
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            # Format: file:line_number:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({
                    "file": parts[0],
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "text": parts[2]
                })
            elif len(parts) == 2:
                # Single file search: line_number:content
                matches.append({
                    "file": path,
                    "line": int(parts[0]) if parts[0].isdigit() else 0,
                    "text": parts[1]
                })
        result["matches"] = matches
        result["count"] = len(matches)
    except Exception as e:
        logger.error(f"search_text failed: {e}")
        result["error"] = str(e)
    
    return result
