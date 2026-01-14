# SSH MCP Server

A Model Context Protocol (MCP) server that lets an agent connect to remote machines over SSH and perform common DevOps tasks. It supports local execution (stdio) and remote deployment over HTTP (Streamable HTTP and SSE).

## Quickstart

### Docker (recommended)

```bash
# Build
docker build -t ssh-mcp .

# Run (persist SSH keys)
docker volume create ssh-data
docker run -p 8000:8000 -v ssh-data:/data --name ssh-mcp ssh-mcp
```

HTTP endpoints:
- Streamable HTTP: `http://localhost:8000/mcp`
- SSE: `http://localhost:8000/sse`

### Local

```bash
pip install .

# Stdio mode (for local MCP hosts)
python -m ssh_mcp

# Combined HTTP server (recommended if you want both /mcp and /sse)
uvicorn ssh_mcp.server_all:app --host 0.0.0.0 --port 8000

# Streamable HTTP only
uvicorn ssh_mcp.server_http:app --host 0.0.0.0 --port 8000

# SSE only
uvicorn ssh_mcp.server_sse:app --host 0.0.0.0 --port 8000
```

## Tool Reference

All tools are exposed via MCP. In HTTP modes (Streamable HTTP or SSE), tools operate within the current MCP session.

### Core

- `connect(host, username, port=22, private_key_path=None, password=None, alias="primary", via=None)`
  - Open an SSH connection and store it under `alias`.
  - `via` optionally specifies a jump host alias (see Jump Hosts).
- `disconnect(alias=None)`
  - Disconnect one alias (e.g. `"web1"`) or all connections if `alias` is omitted.
- `identity()`
  - Returns the server’s public SSH key (Ed25519) for `authorized_keys`.

### Remote execution

- `run(command, target="primary")`
  - Execute a shell command on `target`.
- `info(target="primary")`
  - Basic OS/kernel/shell info.

### Files

- `read(path, target="primary")`
  - Read a remote file.
- `write(path, content, target="primary")`
  - Create/overwrite a remote file.
- `edit(path, old_text, new_text, target="primary")`
  - Safe text replacement (fails if `old_text` is missing or ambiguous).
- `list(path, target="primary")`
  - List a remote directory (JSON).

### Bridging (node ↔ node)

- `sync(source_node, source_path, dest_node, dest_path)`
  - Streams a file from `source_node` to `dest_node` via the MCP server.
  - This works even if the two nodes cannot reach each other directly.

### Observability

- `usage(target="primary")`
  - Structured system snapshot (loadavg/memory/disk).
- `logs(path, lines=50, grep=None, target="primary")`
  - Tail a file with safety limits (useful for large logs).
- `ps(sort_by="cpu", limit=10, target="primary")`
  - Top processes by CPU or memory.

### Docker (requires Docker installed on the target)

- `docker_ps(all=False, target="primary")`
  - Structured container list.
- `docker_logs(container_id, lines=50, target="primary")`
  - Tail container logs.
- `docker_op(container_id, action, target="primary")`
  - `action` is `start`, `stop`, or `restart`.

### Network

- `net_stat(port=None, target="primary")`
  - Structured listeners (tries `ss` first, then `netstat`).
- `net_dump(interface="any", count=20, filter="", target="primary")`
  - Bounded tcpdump capture (requires `tcpdump` on the target and typically passwordless sudo).
- `curl(url, method="GET", target="primary")`
  - Connectivity check from the target.

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

## Architecture

### Data flow (Streamable HTTP)

- Clients connect to the Streamable HTTP endpoint: `/mcp`
- Tool calls and results are carried over the MCP Streamable HTTP transport

### Data flow (SSE)

- The MCP host opens an SSE session: `GET /sse`
- Tool calls are sent as JSON-RPC: `POST /messages?session_id=...`
- Tool results stream back over SSE

### State model

- Each MCP session gets its own `SSHManager` instance.
- Each `SSHManager` can hold multiple SSH connections keyed by `alias`.

### Code layout

```text
src/ssh_mcp/
├── server.py           # stdio server (FastMCP)
├── server_sse.py       # SSE server (FastMCP)
├── server_http.py      # Streamable HTTP server (FastMCP)
├── server_all.py       # Combined HTTP server (/mcp + /sse)
├── ssh_manager.py      # multi-connection SSH engine + sync + jump host
└── tools/
    ├── files.py        # read/write/edit/list wrappers
    ├── system.py       # run/info wrappers
    ├── monitoring.py   # usage/logs/ps
    ├── docker.py       # docker_ps/docker_logs/docker_op
    └── network.py      # net_stat/net_dump/curl
```

## Notes

- The network and monitoring tools depend on standard Linux utilities. Some features (like `tcpdump`) may require installing packages on the target and configuring sudo.
- Docker tools require Docker to be installed on the target host.

## License

MIT
