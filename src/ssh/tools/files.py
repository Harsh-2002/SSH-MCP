from ..ssh_manager import SSHManager
import json

async def read_file(manager: SSHManager, path: str, target: str | None = None) -> str:
    """Read contents of a file."""
    return await manager.read_file(path, target=target)

async def write_file(manager: SSHManager, path: str, content: str, target: str | None = None) -> str:
    """Write content to a file."""
    return await manager.write_file(path, content, target=target)

async def list_directory(manager: SSHManager, path: str, target: str | None = None) -> str:
    """List files in a directory."""
    files = await manager.list_files(path, target=target)
    return json.dumps(files, indent=2)

async def edit_file(manager: SSHManager, path: str, old_text: str, new_text: str, target: str | None = None) -> str:
    """
    Safely replace a block of text in a file.
    Fails if old_text is not found or is ambiguous (found multiple times).
    """
    # 1. Read file
    content = await manager.read_file(path, target=target)
    
    # 2. Check occurrences
    count = content.count(old_text)
    if count == 0:
        raise ValueError(f"Could not find exact match for old_text in {path}")
    if count > 1:
        raise ValueError(f"Found {count} occurrences of old_text. Please provide more context to be unique.")
    
    # 3. Replace
    new_content = content.replace(old_text, new_text)
    
    # 4. Write back
    await manager.write_file(path, new_content, target=target)
    
    return "File updated successfully."
