from ..ssh_manager import SSHManager

async def get_system_info(manager: SSHManager, target: str | None = None) -> str:
    """Returns basic system info (OS, Kernel, Shell)."""
    commands = [
        "uname -sr",
        "cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        "echo $SHELL"
    ]
    
    # We run them as a single command for speed
    full_cmd = " && echo '|||' && ".join(commands)
    
    output = await manager.run(full_cmd, target=target)
    
    # Simple parsing logic (robustness depends on the shell)
    # Output format roughly:
    # Linux 5.15
    # |||
    # Ubuntu 22.04
    # |||
    # /bin/bash
    
    return f"System Info Raw Output:\n{output}"

async def run_command(manager: SSHManager, command: str, target: str | None = None, timeout: float | None = None) -> str:
    """Run a generic command with optional custom timeout."""
    return await manager.run(command, target=target, timeout=timeout)

