import asyncio
import logging
import asyncssh
import sys
import os
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

logger = logging.getLogger("ssh-mcp")

class SSHManager:
    def __init__(self, allowed_root: str = "/"):
        # Reduce very verbose default logging from asyncssh unless explicitly enabled
        if os.getenv("SSH_MCP_DEBUG_ASYNCSSH") not in {"1", "true", "yes", "on"}:
            logging.getLogger("asyncssh").setLevel(logging.WARNING)

        self.connections: Dict[str, asyncssh.SSHClientConnection] = {}
        self.cwds: Dict[str, str] = {}
        self.primary_alias: Optional[str] = None

        # Global lock (connect/disconnect + credential updates)
        self._lock = asyncio.Lock()

        # Per-alias lock to keep cwd/state consistent per target
        self._alias_locks: Dict[str, asyncio.Lock] = {}
        
        # State persistence for auto-reconnect
        self._credentials: Dict[str, Dict[str, Any]] = {}
        
        # Security Policy
        self.allowed_root = os.path.abspath(allowed_root)

        # Global System Key Management
        # Hardcoded to standard persistence path
        self.system_key_path = "/data/id_ed25519"
        
        # Only attempt to generate/use system key if /data exists (Docker/Production)
        # or if we are in a dev environment where we can create it.
        try:
            self._ensure_system_key()
        except Exception as e:
            # Fallback for local dev without /data access: use ~/.ssh-mcp/
            home_key = os.path.expanduser("~/.ssh-mcp/id_ed25519")
            logger.info(f"Could not use /data ({e}), falling back to local storage: {home_key}")
            self.system_key_path = home_key
            self._ensure_system_key()

    def _get_alias_lock(self, alias: str) -> asyncio.Lock:
        lock = self._alias_locks.get(alias)
        if lock is None:
            lock = asyncio.Lock()
            self._alias_locks[alias] = lock
        return lock

    @asynccontextmanager
    async def _alias_lock_ctx(self, aliases: List[str]):
        names = sorted(dict.fromkeys(aliases))
        locks = [self._get_alias_lock(name) for name in names]
        try:
            for lock in locks:
                await lock.acquire()
            yield
        finally:
            for lock in reversed(locks):
                lock.release()

    def _creds_equal(self, existing: Dict[str, Any], new: Dict[str, Any]) -> bool:
        fields = ["host", "username", "port", "private_key_path", "password", "via"]
        return all(existing.get(k) == new.get(k) for k in fields)

    def _ensure_system_key(self):
        """Ensure the global system key exists."""
        key_dir = os.path.dirname(self.system_key_path)
        if not os.path.exists(key_dir):
            try:
                os.makedirs(key_dir, mode=0o700, exist_ok=True)
            except OSError as e:
                # Raise so caller can fall back to a different location
                raise OSError(f"Could not create key directory {key_dir}: {e}") from e

        if not os.access(key_dir, os.W_OK):
            raise PermissionError(f"Key directory is not writable: {key_dir}")
        
        if not os.path.exists(self.system_key_path):
            try:
                logger.info(f"Generating new system key pair at {self.system_key_path}...")
                # Generate a new key pair (Ed25519 is standard, short, and secure)
                key = asyncssh.generate_private_key("ssh-ed25519", comment="Origon")
                
                # Write Private Key
                with open(self.system_key_path, "wb") as f:
                    f.write(key.export_private_key())
                os.chmod(self.system_key_path, 0o600)
                
                # Write Public Key
                with open(self.system_key_path + ".pub", "wb") as f:
                    f.write(key.export_public_key())
                
                logger.info("System key generated successfully.")
            except Exception as e:
                logger.error(f"Failed to generate system key: {e}")

    def get_public_key(self) -> str:
        """Return the public key for authorized_keys."""
        pub_path = self.system_key_path + ".pub"
        if os.path.exists(pub_path):
            with open(pub_path, 'r') as f:
                return f.read().strip()
        return "Error: System key not generated yet. Check server logs."

    def _validate_path(self, path: str, alias: str) -> str:
        """
        Security Check: Ensure path is within allowed_root.
        Returns absolute path if valid, raises PermissionError if not.
        """
        cwd = self.cwds.get(alias, ".")

        # Handle relative paths
        if not path.startswith("/"):
            path = os.path.join(cwd, path)
        
        abs_path = os.path.abspath(path)
        
        # Check traversal
        if not abs_path.startswith(self.allowed_root):
            raise PermissionError(f"Access Denied: Path '{path}' resolves to '{abs_path}', which is outside the allowed root '{self.allowed_root}'.")
        
        return abs_path

    def _get_alias_lock(self, alias: str) -> asyncio.Lock:
        lock = self._alias_locks.get(alias)
        if lock is None:
            lock = asyncio.Lock()
            self._alias_locks[alias] = lock
        return lock

    async def connect(self, host: str, username: str, port: int = 22, 
                      private_key_path: Optional[str] = None, 
                      password: Optional[str] = None,
                      alias: str = "primary",
                      via: Optional[str] = None) -> str:
        """
        Establishes an SSH connection and saves credentials for auto-reconnect.

        Args:
            alias: Connection name ("web1", "db1", etc.).
            via: Optional jump host alias. If set, the connection is tunneled over
                 the existing SSH connection named by `via`.
        """
        async with self._lock:
            if via == alias:
                raise ValueError("'via' cannot be the same as 'alias'.")

            # Fallback to System Key if no auth provided
            used_key_path = private_key_path
            
            # Smart Connect Logic
            if not private_key_path and not password:
                if os.path.exists(self.system_key_path):
                    used_key_path = self.system_key_path
                    logger.info(f"Using system key for auth: {self.system_key_path}")
            
            new_creds = {
                "host": host,
                "username": username,
                "port": port,
                "private_key_path": used_key_path,
                "password": password,
                "via": via,
            }

            existing = self._credentials.get(alias)
            if existing and alias in self.connections and self._creds_equal(existing, new_creds):
                logger.info(f"Alias '{alias}' already connected to {username}@{host}. Reusing existing session.")
                return f"Already connected to {username}@{host} (alias: {alias})"

            # Save credentials for later
            self._credentials[alias] = new_creds
            logger.info(f"Connecting to {username}@{host}:{port} as '{alias}' (via={via})...")
            msg = await self._connect_internal(alias)
            
            if not self.primary_alias:
                self.primary_alias = alias
            elif alias == "primary":
                self.primary_alias = "primary"
                
            return msg

    async def _connect_internal(self, alias: str) -> str:
        """Internal connection logic using stored credentials."""
        if alias in self.connections:
            try:
                self.connections[alias].close()
                await self.connections[alias].wait_closed()
            except: pass
            if alias in self.connections:
                del self.connections[alias]
        
        c = self._credentials.get(alias)
        if not c:
            raise ValueError(f"No credentials found for alias '{alias}'")

        client_keys = None
        
        # Load Private Key if specified
        if c.get("private_key_path"):
            try:
                # asyncssh.read_private_key handles file paths directly in newer versions, 
                # but explicit read is safer for various formats
                client_keys = [asyncssh.read_private_key(c["private_key_path"])]
            except Exception as e:
                logger.error(f"Failed to load key: {e}")
                raise ValueError(f"Failed to load private key at {c['private_key_path']}: {str(e)}")

        try:
            tunnel = None
            if c.get("via"):
                via_alias = c["via"]
                await self._ensure_connection(via_alias)
                tunnel = self.connections.get(via_alias)
                if not tunnel:
                    raise ConnectionError(f"Jump host '{via_alias}' is not connected.")

            conn = await asyncssh.connect(
                c["host"], 
                port=c["port"], 
                username=c["username"], 
                password=c["password"], 
                client_keys=client_keys,
                known_hosts=None,
                tunnel=tunnel,
            )
            
            self.connections[alias] = conn
            
            # Reset CWD
            result = await conn.run("pwd")
            self.cwds[alias] = self._coerce_text(result.stdout).strip()
            
            msg = f"Connected to {c['username']}@{c['host']} (alias: {alias})"
            logger.info(msg)
            return msg

        except Exception as e:
            if alias in self.connections:
                del self.connections[alias]
            logger.warning(f"Connection failed for {c.get('username')}@{c.get('host')}: {e}")
            raise ConnectionError(f"Failed to connect: {str(e)}")

    async def _ensure_connection(self, alias: str):
        """Auto-reconnect if connection is dropped."""
        if alias in self.connections:
            return

        if alias in self._credentials:
            logger.info(f"Connection '{alias}' lost. Attempting auto-reconnect...")
            await self._connect_internal(alias)
        else:
            raise ConnectionError(f"Not connected and no credentials saved for alias '{alias}'.")

    async def disconnect(self, alias: Optional[str] = None) -> str:
        async with self._lock:
            if alias:
                if alias in self.connections:
                    conn = self.connections[alias]
                    conn.close()
                    await conn.wait_closed()
                    del self.connections[alias]
                    if alias in self._credentials:
                        del self._credentials[alias]
                    
                    if self.primary_alias == alias:
                         self.primary_alias = next(iter(self.connections), None)
                    
                    return f"Disconnected '{alias}'."
                return f"No active connection for '{alias}'."
            else:
                # Disconnect all
                count = 0
                for a in list(self.connections.keys()):
                    conn = self.connections[a]
                    conn.close()
                    await conn.wait_closed()
                    del self.connections[a]
                    count += 1
                self._credentials.clear()
                self.primary_alias = None
                return f"Disconnected all ({count}) sessions."

    def _resolve_alias(self, target: Optional[str]) -> str:
        if target:
            return target
        if self.primary_alias:
            return self.primary_alias
        raise ConnectionError("No active connection and no target specified.")

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    async def run_result(self, command: str, retry: bool = True, target: Optional[str] = None) -> Dict[str, Any]:
        """Run a command and return structured results."""
        alias = self._resolve_alias(target)
        async with self._alias_lock_ctx([alias]):
            await self._ensure_connection(alias)

            conn = self.connections.get(alias)
            if not conn:
                raise ConnectionError(f"Not connected to '{alias}'.")

            cwd = self.cwds.get(alias, ".")
            logger.info(f"Executing command on '{alias}': {command}")

            TIMEOUT = 60.0
            cwd_delimiter = "___MCP_CWD_CAPTURE___"

            wrapped_command = (
                f'cd "{cwd}" && '
                f'( {command} ); LAST_EXIT_CODE=$?; '
                f'echo "{cwd_delimiter}"; pwd; '
                f'exit $LAST_EXIT_CODE'
            )

            try:
                result = await asyncio.wait_for(conn.run(wrapped_command), timeout=TIMEOUT)
            except (asyncssh.ConnectionLost, BrokenPipeError, ConnectionResetError):
                if retry:
                    logger.warning(f"SSH Connection '{alias}' lost during execution. Reconnecting...")
                    if alias in self.connections:
                        del self.connections[alias]
                    await self._ensure_connection(alias)
                    return await self.run_result(command, retry=False, target=alias)
                raise
            except asyncio.TimeoutError:
                logger.error(f"Command timed out: {command}")
                raise TimeoutError(f"Command timed out after {TIMEOUT} seconds.")
            except Exception as e:
                logger.error(f"Execution error: {e}")
                raise RuntimeError(f"SSH Execution Error: {str(e)}")

            stdout = self._coerce_text(result.stdout)
            stderr = self._coerce_text(result.stderr)
            exit_code = result.exit_status

            # Update CWD using delimiter
            clean_stdout = stdout
            if cwd_delimiter in stdout:
                parts = stdout.split(cwd_delimiter)
                clean_stdout = parts[0]
                if len(parts) > 1:
                    candidate = parts[1].strip()
                    if candidate:
                        self.cwds[alias] = candidate

            return {
                "target": alias,
                "stdout": clean_stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "cwd": self.cwds.get(alias, cwd),
            }

    async def execute(self, command: str, retry: bool = True, target: Optional[str] = None) -> str:
        """Run a command and return a human-readable string."""
        res = await self.run_result(command, retry=retry, target=target)

        output_parts: List[str] = []
        if res["stdout"]:
            output_parts.append(f"STDOUT:\n{res['stdout'].rstrip()}")
        if res["stderr"]:
            output_parts.append(f"STDERR:\n{res['stderr'].rstrip()}")

        final_output = "\n\n".join(output_parts) or "(No output)"

        MAX_LEN = 4000
        if len(final_output) > MAX_LEN:
            final_output = final_output[:MAX_LEN] + "\n... [Output truncated]"

        if res["exit_code"] != 0:
            final_output += f"\n\n[Exit Code: {res['exit_code']}]"

        return final_output

    # --- SFTP Operations (With Reconnect & Security) ---

    async def list_files(self, path: str, retry: bool = True, target: Optional[str] = None) -> List[Dict[str, Any]]:
        alias = self._resolve_alias(target)
        async with self._alias_lock_ctx([alias]):
            try:
                await self._ensure_connection(alias)
                safe_path = self._validate_path(path, alias)
                logger.info(f"Listing directory on '{alias}': {safe_path}")

                conn = self.connections[alias]
                async with conn.start_sftp_client() as sftp:
                    files = await sftp.readdir(safe_path)
                    result = []
                    for f in files:
                        ftype = "dir" if f.attrs.permissions and (f.attrs.permissions & 0o40000) else "file"
                        result.append({
                            "name": str(f.filename),
                            "type": ftype,
                            "size": f.attrs.size,
                            "permissions": oct(f.attrs.permissions) if f.attrs.permissions else "unknown"
                        })
                    return result
            except (asyncssh.ConnectionLost, BrokenPipeError):
                if retry:
                    if alias in self.connections:
                        del self.connections[alias]
                    await self._ensure_connection(alias)
                    return await self.list_files(path, retry=False, target=alias)
                raise

    async def read_file(self, path: str, retry: bool = True, target: Optional[str] = None) -> str:
        alias = self._resolve_alias(target)
        async with self._alias_lock_ctx([alias]):
            try:
                await self._ensure_connection(alias)
                safe_path = self._validate_path(path, alias)
                logger.info(f"Reading file on '{alias}': {safe_path}")

                conn = self.connections[alias]
                async with conn.start_sftp_client() as sftp:
                    async with sftp.open(safe_path, 'r') as f:
                        content = await f.read()
                        if isinstance(content, bytes):
                            return content.decode('utf-8')
                        return str(content)
            except (asyncssh.ConnectionLost, BrokenPipeError):
                if retry:
                    if alias in self.connections:
                        del self.connections[alias]
                    await self._ensure_connection(alias)
                    return await self.read_file(path, retry=False, target=alias)
                raise

    async def write_file(self, path: str, content: str, retry: bool = True, target: Optional[str] = None) -> str:
        alias = self._resolve_alias(target)
        async with self._alias_lock_ctx([alias]):
            try:
                await self._ensure_connection(alias)
                safe_path = self._validate_path(path, alias)
                logger.info(f"Writing file on '{alias}': {safe_path} ({len(content)} bytes)")

                conn = self.connections[alias]
                async with conn.start_sftp_client() as sftp:
                    async with sftp.open(safe_path, 'w') as f:
                        await f.write(content)
                return f"Successfully wrote to {safe_path}"
            except (asyncssh.ConnectionLost, BrokenPipeError):
                if retry:
                    if alias in self.connections:
                        del self.connections[alias]
                    await self._ensure_connection(alias)
                    return await self.write_file(path, content, retry=False, target=alias)
                raise

    async def sync(self, source_node: str, source_path: str, dest_node: str, dest_path: str) -> str:
        """Stream file from source_node to dest_node efficiently."""

        aliases = [source_node, dest_node]
        async with self._alias_lock_ctx(aliases):
            # Verify both connections
            await self._ensure_connection(source_node)
            await self._ensure_connection(dest_node)

            conn_src = self.connections[source_node]
            conn_dest = self.connections[dest_node]

            # Validate paths (basic check)
            src_safe = self._validate_path(source_path, source_node)
            dest_safe = self._validate_path(dest_path, dest_node)

            logger.info(f"Syncing {source_node}:{src_safe} -> {dest_node}:{dest_safe}")

            try:
                async with conn_src.start_sftp_client() as sftp_src, \
                           conn_dest.start_sftp_client() as sftp_dest:

                    # Open source for reading
                    async with sftp_src.open(src_safe, 'rb') as f_src:
                        # Open dest for writing
                        async with sftp_dest.open(dest_safe, 'wb') as f_dest:
                            # Stream data in 64KB chunks
                            CHUNK_SIZE = 64 * 1024
                            total_bytes = 0
                            while True:
                                data = await f_src.read(CHUNK_SIZE)
                                if not data:
                                    break
                                await f_dest.write(data)
                                total_bytes += len(data)

                return f"Successfully synced {total_bytes} bytes from {source_node} to {dest_node}."

            except Exception as e:
                logger.error(f"Sync failed: {e}")
                raise RuntimeError(f"Sync failed: {str(e)}")
