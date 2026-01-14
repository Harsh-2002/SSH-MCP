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
| `run(command)` | Execute shell command |
| `info()` | Get OS/kernel/shell info |

### File Operations
| Tool | Description |
|------|-------------|
| `read(path)` | Read remote file content |
| `write(path, content)` | Create/overwrite remote file |
| `edit(path, old_text, new_text)` | Safe text replacement |
| `list(path)` | List directory contents (JSON) |

### Service Management
| Tool | Description |
|------|-------------|
| `inspect_service(name)` | Auto-detect Docker/Systemd/OpenRC status |
| `list_services(failed_only)` | List running or failed services |
| `fetch_logs(service_name, lines, error_only)` | Smart log aggregation |
| `service_action(name, action)` | Start/stop/restart services or containers |

### Docker
| Tool | Description |
|------|-------------|
| `docker_ps(all)` | List containers |
| `docker_logs(container_id, lines)` | Get container logs |
| `docker_op(container_id, action)` | Start/stop/restart container |
| `docker_ip(container_name)` | Get container IP address(es) |
| `docker_find_by_ip(ip_address)` | Find container by IP |
| `docker_networks()` | List networks and their containers |

### Database (Container-Aware)
| Tool | Description |
|------|-------------|
| `list_db_containers()` | Find database containers |
| `db_schema(container, db_type, database)` | Get table list (postgres/mysql/scylladb) |
| `db_describe_table(container, db_type, table)` | Get table structure |
| `db_query(container, db_type, query)` | Execute SQL/CQL query |

### Package Manager
| Tool | Description |
|------|-------------|
| `install_package(packages)` | Install packages (apt/apk/dnf auto-detected) |
| `remove_package(packages)` | Remove packages |
| `search_package(query)` | Search available packages |
| `list_installed(grep)` | List installed packages |

### Network & Connectivity
| Tool | Description |
|------|-------------|
| `net_stat(port)` | List listening ports |
| `net_dump(interface, count, filter)` | Capture network traffic (tcpdump) |
| `curl(url, method)` | Check URL connectivity |
| `test_connection(host, port, timeout)` | Verify TCP connectivity between services |
| `check_port_owner(port)` | Find process listening on port |
| `scan_ports(host, ports)` | Quick multi-port scan |

### System Diagnostics
| Tool | Description |
|------|-------------|
| `usage()` | System resource usage (CPU/RAM/Disk) |
| `logs(path, lines, grep)` | Tail log files |
| `ps(sort_by, limit)` | Top processes |
| `list_scheduled_tasks()` | Unified cron + systemd timers view |
| `hunt_zombies()` | Find defunct processes |
| `hunt_io_hogs(limit)` | Find processes in I/O wait |
| `check_system_health()` | Quick health overview |
| `check_oom_events(lines)` | Recent OOM kills from kernel |

### Disk Analysis
| Tool | Description |
|------|-------------|
| `find_large_files(path, limit, min_size)` | Find largest files recursively |
| `find_large_folders(path, limit, max_depth)` | Find largest folders |
| `disk_usage_summary()` | All mounted filesystem usage |
| `find_old_files(path, days, limit)` | Find stale files |
| `find_recently_modified(path, minutes, limit)` | Track recent changes |

### Outage Prevention
| Tool | Description |
|------|-------------|
| `check_ssl_cert(host, port)` | Check SSL cert expiry (days until expiration) |
| `check_dns(hostname)` | Verify DNS resolution from target |
| `check_ulimits()` | Check resource limits (open files, max processes) |
| `check_network_errors()` | Check network interfaces for drops/errors |

### Fleet Bulk Operations
Run operations across multiple connected hosts simultaneously. All bulk tools accept a `targets` parameter (list of connection aliases).

| Tool | Description |
|------|-------------|
| `bulk_run(command, targets)` | Run same command on multiple hosts |
| `bulk_read(path, targets)` | Read file from multiple hosts (compare configs) |
| `bulk_write(path, content, targets)` | Deploy file to multiple hosts |
| `bulk_edit(path, old, new, targets)` | Mass config update (e.g., Nginx) |
| `bulk_docker_ps(all, targets)` | Cluster-wide container inventory |
| `bulk_usage(targets)` | Resource usage from all hosts |
| `bulk_service(name, action, targets)` | Restart service on all hosts |
| `bulk_install(packages, targets)` | Install packages fleet-wide |
| `bulk_connectivity(host, port, targets)` | Verify all hosts can reach a service |
| `bulk_health(targets)` | System health from all hosts |
| `bulk_zombies(targets)` | Find zombies fleet-wide |
| `bulk_disk(targets)` | Disk usage from all hosts |
| `bulk_remove_package(packages, targets)` | Uninstall packages fleet-wide |
| `bulk_db_query(container, db_type, query, targets)` | Run SQL/CQL across replicas |
| `bulk_oom_check(lines, targets)` | OOM events from all hosts |
| `bulk_find_large_files(path, limit, targets)` | Find disk hogs fleet-wide |
| `bulk_ssl_check(host, port, targets)` | SSL cert expiry from all hosts |
| `bulk_dns_check(hostname, targets)` | DNS resolution from all hosts |

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

### Data flow (Streamable HTTP)

- Clients connect to the Streamable HTTP endpoint: `/mcp`
- Tool calls and results are carried over the MCP Streamable HTTP transport

### Data flow (SSE)

- The MCP host opens an SSE session: `GET /sse`
- Tool calls are sent as JSON-RPC: `POST /messages?session_id=...`
- Tool results stream back over SSE

### State model

- The server uses the selected strategy (Standard, Header, or Global) to determine which `SSHManager` to use.
- Each `SSHManager` holds multiple SSH connections keyed by `alias`.

### Stateless agents

*Removed legacy section - see "Session Persistence Strategies" above.*

### Code layout

```text
src/ssh_mcp/
├── server.py             # stdio server (FastMCP)
├── server_sse.py         # SSE server (FastMCP)
├── server_http.py        # Streamable HTTP server (FastMCP)
├── server_all.py         # Combined HTTP server (/mcp + /sse)
├── ssh_manager.py        # multi-connection SSH engine + sync + jump host
├── session_store.py      # connection pooling for stateless agents
└── tools/
    ├── base.py           # OS/init system detection helpers
    ├── files.py          # read/write/edit/list
    ├── files_advanced.py # large file finder, disk analysis
    ├── system.py         # run/info
    ├── monitoring.py     # usage/logs/ps
    ├── docker.py         # containers, IPs, networks
    ├── network.py        # net_stat/net_dump/curl
    ├── net_debug.py      # connectivity testing
    ├── diagnostics.py    # scheduled tasks, zombies, OOM
    ├── services_universal.py  # Systemd/OpenRC/Docker services
    ├── db.py             # database queries (postgres/mysql/scylla)
    └── pkg.py            # package manager (apt/apk/dnf)
```

## Notes

- The network and monitoring tools depend on standard Linux utilities. Some features (like `tcpdump`) may require installing packages on the target and configuring sudo.
- Docker tools require Docker to be installed on the target host.

## License

MIT
