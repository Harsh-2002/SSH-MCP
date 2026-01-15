# SSH MCP Server

A Model Context Protocol (MCP) server that lets an agent connect to remote machines over SSH and perform common DevOps tasks. It supports local execution (stdio) and remote deployment over HTTP using Streamable HTTP transport.

## Quickstart

### Docker (recommended)

```bash
# Build
docker build -t ssh-mcp .

# Run (persist SSH keys)
docker volume create ssh-data
docker run -p 8000:8000 -v ssh-data:/data --name ssh-mcp ssh-mcp
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

## Tool Reference

All tools are exposed via MCP. Each tool accepts a `target` parameter (default: `"primary"`) to specify which SSH connection to use.

### Core Tools
| Tool | Description |
|------|-------------|
| `connect(host, username, port, alias, via)` | Open SSH connection to a remote server |
| `disconnect(alias)` | Close one or all SSH connections |
| `identity()` | Get server's public SSH key for authorized_keys |
| `sync(source_node, source_path, dest_node, dest_path)` | Stream file between two nodes |

### Remote Execution
| Tool | Description |
|------|-------------|
| `run(command)` | Execute any shell command |
| `info()` | Get OS/kernel/shell info |

### File Operations
| Tool | Description |
|------|-------------|
| `read(path)` | Read remote file content |
| `write(path, content)` | Create/overwrite remote file |
| `edit(path, old_text, new_text)` | Safe text replacement |
| `list_dir(path)` | List directory contents (JSON) |

### Discovery
| Tool | Description |
|------|-------------|
| `docker_ps(all)` | List Docker containers |
| `net_stat(port)` | List listening ports |
| `list_services(failed_only)` | List system services (Systemd/OpenRC) |

### Monitoring
| Tool | Description |
|------|-------------|
| `usage()` | System resource usage (CPU/RAM/Disk) |
| `logs(path, lines, grep)` | Tail log files |
| `ps(sort_by, limit)` | Top processes |

### Database
| Tool | Description |
|------|-------------|
| `db_query(container, db_type, query, ...)` | Execute SQL/CQL/MongoDB query in container |
| `db_schema(container, db_type, database, ...)` | Get database schema (tables/collections) |
| `db_describe_table(container, db_type, table, ...)` | Describe table/collection structure |
| `list_db_containers()` | Find database containers |

**Supported databases:** PostgreSQL, MySQL, ScyllaDB, Cassandra, MongoDB

**db_query options:**
- `timeout` (default: 60s) - Query timeout
- `read_only` (default: false) - Block destructive queries
- `max_rows` (default: 1000) - Limit result rows

## Multi-node usage

You can connect to multiple hosts in a single session by choosing different `alias` values.

Example:

1) Connect two servers:
- `connect(host="10.0.0.10", username="ubuntu", alias="web1")`
- `connect(host="10.0.0.11", username="ubuntu", alias="web2")`

2) Run commands on a specific node:
- `run("uptime", target="web1")`
- `run("df -h", target="web2")`

3) Copy a file across nodes (even if they can’t reach each other):
- `sync(source_node="web1", source_path="/var/log/nginx/access.log", dest_node="web2", dest_path="/tmp/web1-access.log")`

## Jump hosts (bastion)

If a node is not reachable directly from where the MCP server runs, you can connect through a jump host.

Example:

1) Connect the bastion:
- `connect(host="bastion.company.com", username="ubuntu", alias="bastion")`

2) Connect a private node through the bastion:
- `connect(host="10.0.1.25", username="ubuntu", alias="db1", via="bastion")`

From then on, you can use:
- `run("systemctl status postgresql", target="db1")`

## Authentication

By default the server keeps a managed SSH key pair in `/data` (container volume):
- Private key: `/data/id_ed25519`
- Public key: `/data/id_ed25519.pub` (comment: `Origon`)

To use managed identity:
1. Call `identity()` and copy the public key.
2. Add it to `~/.ssh/authorized_keys` on the target host(s).
3. Call `connect(...)` without `password`/`private_key_path`.

You can also provide `password` or `private_key_path` per connection.

## Configuration

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORT` | The port the HTTP server listens on. | `8000` |
| `ALLOWED_ROOT` | Restricts file operations to a specific path. | `/` (unrestricted) |
| `SSH_MCP_GLOBAL_STATE` | If set to `true`, share connections across sessions. | `false` |
| `SSH_MCP_SESSION_HEADER` | Header to use for smart session caching. | `X-Session-Key` |
| `SSH_MCP_SESSION_TIMEOUT` | Idle timeout for cached sessions (seconds). | `300` (5 mins) |

## Architecture

### Session Persistence Strategies

A common challenge with AI Agents is that they are often "stateless" HTTP clients—they open a new connection for every request. By default, this would cause the SSH connection to close and reopen constantly, breaking state (like `cd` commands).

This server solves this with three strategies:

#### 1. Standard Mode (Default)
*   **Behavior**: SSH state is tied to the MCP connection.
*   **Best For**: Desktop apps (Claude Desktop) or agents that keep a persistent WebSocket/SSE connection.

#### 2. Smart Header Mode (Recommended for APIs)
*   **Behavior**: The server caches SSH sessions based on a client-provided header (default: `X-Session-Key`).
*   **How it works**:
    1. Agent sends `X-Session-Key: my-agent-1` with every request.
    2. Server checks its cache. If a session exists for `my-agent-1`, it is reused.
    3. If the agent goes silent for 5 minutes (configurable), the connection is automatically closed.
*   **Best For**: Custom AI Agents, LangChain, or REST-based clients.

#### 3. Global Mode (Force Override)
*   **Behavior**: A single global SSH manager is used for *everyone*.
*   **Config**: Set `SSH_MCP_GLOBAL_STATE=true`.
*   **Best For**: Single-user private instances where you don't want to configure headers.

### Data flow

- Clients connect to the Streamable HTTP endpoint: `/mcp`
- Tool calls and results are carried over the MCP Streamable HTTP transport (the current MCP standard)

### State model

- The server uses the selected strategy (Standard, Header, or Global) to determine which `SSHManager` to use.
- Each `SSHManager` holds multiple SSH connections keyed by `alias`.

### Stateless agents

*Removed legacy section - see "Session Persistence Strategies" above.*

### Code layout

```text
src/ssh/
├── server.py             # stdio server (FastMCP)
├── mcp_server.py         # FastMCP server instance and tool definitions
├── server_all.py         # HTTP server (Streamable HTTP /mcp)
├── ssh_manager.py        # multi-connection SSH engine + sync + jump host
├── session_store.py      # connection pooling for stateless agents
└── tools/
    ├── base.py           # OS/init system detection helpers
    ├── files.py          # read/write/edit/list
    ├── system.py         # run/info
    ├── monitoring.py     # usage/logs/ps
    ├── docker.py         # docker_ps
    ├── network.py        # net_stat
    ├── services_universal.py  # list_services
    └── db.py             # db_query with secure credentials
```

## Notes

- Some commands (like `tcpdump`) may require installing packages on the target and configuring sudo.
- Docker tools require Docker to be installed on the target host.

## License

MIT
