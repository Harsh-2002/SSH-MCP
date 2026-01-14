# SSH MCP Server

This is a Model Context Protocol (MCP) server that enables AI agents to connect to and interact with remote servers via SSH. It supports both local execution (stdio) and remote deployment (SSE).

## Capabilities

The server exposes the following tools to the connected agent:

*   **`connect`**: Establish an SSH session with a remote host. Supports password, private key, or managed system identity.
*   **`run`**: Execute shell commands on the connected server.
*   **`read`**: Read the contents of a remote file.
*   **`write`**: Create or overwrite a remote file.
*   **`edit`**: Replace a specific block of text in a file (useful for configuration updates).
*   **`list`**: List files in a directory with metadata.
*   **`info`**: Retrieve basic OS and kernel information.
*   **`identity`**: Retrieve the server's public key for whitelisting.

## Usage

### Docker (Recommended)

Running via Docker ensures a clean environment and simplifies key persistence.

```bash
# Build the image
docker build -t ssh-mcp .

# Run the server (mounting a volume for keys)
docker volume create ssh-data
docker run -p 8000:8000 -v ssh-data:/data ssh-mcp
```

The server will be available at `http://localhost:8000/sse`.

### Local Installation

You can also run the server directly using Python.

```bash
pip install .

# Mode 1: CLI (Stdio) - For use with local clients like Claude Desktop
python -m ssh_mcp

# Mode 2: Server (SSE) - For network access
uvicorn ssh_mcp.server_sse:app --host 0.0.0.0 --port 8000
```

## Configuration

The server can be configured via environment variables, though defaults are sufficient for most use cases.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORT` | The port the SSE server listens on. | `8000` |
| `ALLOWED_ROOT` | Restricts file operations to a specific path (e.g., `/home/user`). | `/` (Unrestricted) |

## Authentication

The server manages its own SSH identity to facilitate connections without passing private keys through the agent context.

1.  **System Key**: On first run, the server generates an Ed25519 key pair in `/data`.
2.  **Whitelisting**: You can ask the agent to provide its public key (via the `identity` tool) and add it to your target server's `~/.ssh/authorized_keys`.
3.  **Connection**: The agent can then connect using the system identity by omitting credentials.

Custom private keys and passwords are also supported for specific sessions.

## Architecture

The project is structured for modularity, security, and high concurrency:

```text
src/ssh_mcp/
├── server_sse.py       # SaaS/Cloud Entry Point (FastAPI)
├── server.py           # CLI Entry Point (Stdio)
├── ssh_manager.py      # Core Logic (Connection, Auth, Reconnect)
└── tools/              # Capability Modules
    ├── files.py        # SFTP Wrappers
    └── system.py       # Command Execution
```

### Concurrency & Scaling

This server is designed for high-concurrency SaaS environments:

1.  **Async I/O**: Built on `asyncio` and `asyncssh`. Waiting for a remote command to finish does *not* block the server. It can handle hundreds of concurrent agents.
2.  **Session Isolation**: In SSE mode, every agent connection is assigned a unique Session ID. The SSH state is stored within this session context. User A's connection to Server X is completely isolated from User B's connection to Server Y.
3.  **Thread Safety**: Internal locks ensure that multiple commands sent by a single agent are queued and executed safely in order.

## Security Model

1.  **Private Keys**: Never leave the container. Stored in `/data`.
2.  **Scopes**: All file operations are validated against `ALLOWED_ROOT`.
3.  **Isolation**: The base Docker image is minimal (`python:3.11-slim`) and lacks an SSH server, preventing agents from connecting back to localhost.
