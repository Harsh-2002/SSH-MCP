from ..ssh_manager import SSHManager

async def get_system_info(manager: SSHManager) -> str:
    """Returns basic system info (OS, Kernel, Shell)."""
    commands = [
        "uname -sr",
        "cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        "echo $SHELL"
    ]
    
    # We run them as a single command for speed
    full_cmd = " && echo '|||' && ".join(commands)
    
    output = await manager.execute(full_cmd)
    
    # Simple parsing logic (robustness depends on the shell)
    # Output format roughly:
    # Linux 5.15
    # |||
    # Ubuntu 22.04
    # |||
    # /bin/bash
    
    return f"System Info Raw Output:\n{output}"

async def run_command(manager: SSHManager, command: str) -> str:
    """Run a generic command."""
    return await manager.execute(command)
