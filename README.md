# SSH MCP Server

A Model Context Protocol (MCP) server that lets an agent connect to remote machines over SSH to manage systems. It supports local execution (stdio) and remote deployment over HTTP using Streamable HTTP transport.

## Quickstart

### Docker (CLI)

```bash
# Pull and run (persisting SSH keys)
docker run -d \
  --name ssh-mcp \
  -p 8000:8000 \
  -v ssh-mcp-data:/data \
  firstfinger/ssh-mcp:latest

# Note: If using a bind mount instead of a named volume, ensure it is writable:
# sudo chown -R 1000:1000 /path/to/your/data
```


### Docker Compose

```bash
# Clone and run
git clone https://github.com/Harsh-2002/SSH-MCP.git
cd SSH-MCP
docker compose up -d
```

HTTP endpoint:
- Streamable HTTP: `http://localhost:8000/mcp`

### Local

```bash
pip install .

# Stdio mode (for local MCP hosts)
python -m ssh

# HTTP server (Streamable HTTP transport)
uvicorn ssh.server_all:app --host 0.0.0.0 --port 8000
```


## How It Works

This server acts as a **bridge** between an AI Agent and your remote infrastructure.

### 1. Direct SSH Bridge & Multi-Node Support
Instead of the agent needing SSH libraries, it calls simple MCP tools. The server handles all connections, authentication, and even allows you to `sync` files between multiple remote nodes directly through its relay.

### 2. Managed Identity (Passwordless Access)
By default, the server generates an Ed25519 key pair in `/data`:
- Private key: `/data/id_ed25519`
- Public key: `/data/id_ed25519.pub`

**To use it:** 
1. Call `identity()` to get the public key.
2. Add it to `~/.ssh/authorized_keys` on your target host(s).
3. Connect without a password.

### 3. Session Persistence Strategies
Since many AI agents are "stateless" HTTP clients, the server uses three strategies to keep SSH connections alive and maintain state (like `cd` commands):

*   **Standard Mode**: (Default) SSH state is tied to the persistent MCP connection (Best for Claude Desktop).
*   **Smart Header Mode**: (Recommended for APIs) Caches sessions based on a client-provided header (e.g., `X-Session-Key: agent-1`). Sessions close after 5 minutes of silence.
*   **Global Mode**: (`SSH_MCP_GLOBAL_STATE=true`) Shares one global manager for all clients. Best for private, single-user instances.

## Tool Reference

All tools accept a `target` parameter (default: `"primary"`) to specify the SSH connection.

### Core & System
| Tool | Description |
|------|-------------|
| `connect(host,...)` | Open SSH connection (supports password, key, or managed identity) |
| `disconnect(alias)` | Close one or all SSH connections |
| `identity()` | Get server's public key for `authorized_keys` |
| `info()` | Get remote OS/kernel/shell information |
| `run(command)` | Execute any shell command |

### File Operations
| Tool | Description |
|------|-------------|
| `read(path)` | Read remote file content |
| `write(path, content)` | Create/overwrite remote file |
| `edit(path, old, new)` | Safe text replacement in a file |
| `list_dir(path)` | List directory contents |
| `sync(src, dst, ...)` | Stream file directly between two remote nodes |

### DevOps & Monitoring
| Tool | Description |
|------|-------------|
| `search_files(pattern)` | Find files using POSIX `find` |
| `search_text(pattern)` | Search in files using `grep` |
| `package_manage(pkg)` | Install/check packages (apt, apk, dnf, yum) |
| `diagnose_system()` | One-click SRE health check (Load, OOM, Disk) |
| `journal_read()` | Read system logs (systemd/syslog) |
| `docker_ps()` | List Docker containers |

### Database
| Tool | Description |
|------|-------------|
| `db_query(...)` | Execute SQL/CQL/MongoDB query in container |
| `db_schema(...)` | Get database/collection schema |
| `list_db_containers()` | Find database containers on host |

**Supported DBs:** PostgreSQL, MySQL, ScyllaDB, Cassandra, MongoDB

## Advanced Usage

### Multi-node orchestration
You can connect to multiple hosts in a single session by using different `alias` values.
```python
connect(host="10.0.0.1", alias="web")
connect(host="10.0.0.2", alias="db")
run("uptime", target="web")
sync(source_node="web", source_path="/log.txt", dest_node="db", dest_path="/tmp/")
```

### Jump hosts
Connect to private nodes through a bastion:
```python
connect(host="bastion.net", alias="jump")
connect(host="10.0.1.5", via="jump", alias="private-srv")
```

## Configuration

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PORT` | Integer | `8000` | The port the HTTP server listens on. |
| `SSH_MCP_SESSION_HEADER` | String | `X-Session-Key` | Header used for smart session caching. |
| `SSH_MCP_SESSION_TIMEOUT` | Integer | `300` | Idle timeout for cached sessions in seconds. |
| `SSH_MCP_GLOBAL_STATE` | Boolean | `false` | If `true`, a single SSH manager is shared by all clients. |
| `SSH_MCP_COMMAND_TIMEOUT` | Float | `120.0` | Maximum time (seconds) allowed for an SSH command. |
| `SSH_MCP_MAX_OUTPUT` | Integer | `51200` | Maximum byte size of command output returned (approx 50KB). |
| `SSH_MCP_DEBUG_ASYNCSSH` | Boolean | `false` | Enable verbose debug logs for the `asyncssh` library. |


## License

MIT
