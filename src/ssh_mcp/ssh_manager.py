import asyncio
import logging
import asyncssh
import sys
import os
from typing import Optional, List, Dict, Any

logger = logging.getLogger("ssh-mcp")

class SSHManager:
    def __init__(self, allowed_root: str = "/"):
        self.conn: Optional[asyncssh.SSHClientConnection] = None
        self.cwd: str = "."
        self._lock = asyncio.Lock()
        
        # State persistence for auto-reconnect
        self._credentials: Dict[str, Any] = {}
        
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

    def _ensure_system_key(self):
        """Ensure the global system key exists."""
        key_dir = os.path.dirname(self.system_key_path)
        if not os.path.exists(key_dir):
            try:
                os.makedirs(key_dir, mode=0o700, exist_ok=True)
            except OSError as e:
                logger.warning(f"Could not create key directory {key_dir}: {e}")
                return
        
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

    def _validate_path(self, path: str) -> str:
        """
        Security Check: Ensure path is within allowed_root.
        Returns absolute path if valid, raises PermissionError if not.
        """
        # Handle relative paths
        if not path.startswith("/"):
            path = os.path.join(self.cwd, path)
        
        abs_path = os.path.abspath(path)
        
        # Check traversal
        if not abs_path.startswith(self.allowed_root):
            raise PermissionError(f"Access Denied: Path '{path}' resolves to '{abs_path}', which is outside the allowed root '{self.allowed_root}'.")
        
        return abs_path

    async def connect(self, host: str, username: str, port: int = 22, 
                      private_key_path: Optional[str] = None, 
                      password: Optional[str] = None) -> str:
        """
        Establishes an SSH connection and saves credentials for auto-reconnect.
        """
        async with self._lock:
            # Fallback to System Key if no auth provided
            used_key_path = private_key_path
            
            # Smart Connect Logic
            if not private_key_path and not password:
                if os.path.exists(self.system_key_path):
                    used_key_path = self.system_key_path
                    logger.info(f"Using system key for auth: {self.system_key_path}")
            
            # Save credentials for later
            self._credentials = {
                "host": host,
                "username": username,
                "port": port,
                "private_key_path": used_key_path,
                "password": password
            }
            logger.info(f"Connecting to {username}@{host}:{port}...")
            return await self._connect_internal()

    async def _connect_internal(self) -> str:
        """Internal connection logic using stored credentials."""
        if self.conn:
            try:
                self.conn.close()
                await self.conn.wait_closed()
            except: pass
            self.conn = None
        
        c = self._credentials
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
            self.conn = await asyncssh.connect(
                c["host"], 
                port=c["port"], 
                username=c["username"], 
                password=c["password"], 
                client_keys=client_keys,
                known_hosts=None
            )
            
            # Reset CWD
            result = await self.conn.run("pwd")
            self.cwd = result.stdout.strip()
            
            msg = f"Connected to {c['username']}@{c['host']}"
            logger.info(msg)
            return msg

        except Exception as e:
            self.conn = None
            logger.warning(f"Connection failed for {c.get('username')}@{c.get('host')}: {e}")
            raise ConnectionError(f"Failed to connect: {str(e)}")

    async def _ensure_connection(self):
        """Auto-reconnect if connection is dropped."""
        if self.conn:
            return

        if self._credentials:
            logger.info("Connection lost. Attempting auto-reconnect...")
            await self._connect_internal()
        else:
            raise ConnectionError("Not connected and no credentials saved.")

    async def disconnect(self) -> str:
        async with self._lock:
            self._credentials = {} # Clear creds so we don't auto-reconnect
            if self.conn:
                logger.info("Disconnecting session.")
                self.conn.close()
                await self.conn.wait_closed()
                self.conn = None
                return "Disconnected."
            return "No active connection."

    async def execute(self, command: str, retry: bool = True) -> str:
        try:
            await self._ensure_connection()
        except Exception:
            if not retry: raise
            # If connect fails, we might just fail out.

        if not self.conn:
            raise ConnectionError("Not connected.")
        
        logger.info(f"Executing command: {command}")

        TIMEOUT = 60.0
        cwd_delimiter = "___MCP_CWD_CAPTURE___"
        
        wrapped_command = (
            f'cd "{self.cwd}" && '
            f'( {command} ); LAST_EXIT_CODE=$?; '
            f'echo "{cwd_delimiter}"; pwd; '
            f'exit $LAST_EXIT_CODE'
        )

        try:
            result = await asyncio.wait_for(
                self.conn.run(wrapped_command), 
                timeout=TIMEOUT
            )
        except (asyncssh.ConnectionLost, BrokenPipeError, ConnectionResetError):
            if retry:
                logger.warning("SSH Connection lost during execution. Reconnecting...")
                self.conn = None
                await self._ensure_connection()
                return await self.execute(command, retry=False)
            raise
        except asyncio.TimeoutError:
            logger.error(f"Command timed out: {command}")
            raise TimeoutError(f"Command timed out after {TIMEOUT} seconds.")
        except Exception as e:
            logger.error(f"Execution error: {e}")
            raise RuntimeError(f"SSH Execution Error: {str(e)}")

        # Output processing
        full_stdout = result.stdout
        stderr = result.stderr
        exit_code = result.exit_status

        clean_stdout = full_stdout
        if cwd_delimiter in full_stdout:
            parts = full_stdout.split(cwd_delimiter)
            clean_stdout = parts[0]
            if len(parts) > 1:
                candidate = parts[1].strip()
                if candidate:
                    self.cwd = candidate

        output_parts = []
        if clean_stdout:
            output_parts.append(f"STDOUT:\n{clean_stdout.rstrip()}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr.rstrip()}")
        
        final_output = "\n\n".join(output_parts) or "(No output)"

        MAX_LEN = 4000
        if len(final_output) > MAX_LEN:
            final_output = final_output[:MAX_LEN] + f"\n... [Output truncated]"

        if exit_code != 0:
            final_output += f"\n\n[Exit Code: {exit_code}]"

        return final_output

    # --- SFTP Operations (With Reconnect & Security) ---

    async def list_files(self, path: str, retry: bool = True) -> List[Dict[str, Any]]:
        try:
            await self._ensure_connection()
            safe_path = self._validate_path(path)
            logger.info(f"Listing directory: {safe_path}")
            
            async with self.conn.start_sftp_client() as sftp:
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
                self.conn = None
                await self._ensure_connection()
                return await self.list_files(path, retry=False)
            raise

    async def read_file(self, path: str, retry: bool = True) -> str:
        try:
            await self._ensure_connection()
            safe_path = self._validate_path(path)
            logger.info(f"Reading file: {safe_path}")
            
            async with self.conn.start_sftp_client() as sftp:
                async with sftp.open(safe_path, 'r') as f:
                    content = await f.read()
                    if isinstance(content, bytes):
                        return content.decode('utf-8')
                    return str(content)
        except (asyncssh.ConnectionLost, BrokenPipeError):
            if retry:
                self.conn = None
                await self._ensure_connection()
                return await self.read_file(path, retry=False)
            raise

    async def write_file(self, path: str, content: str, retry: bool = True) -> str:
        try:
            await self._ensure_connection()
            safe_path = self._validate_path(path)
            logger.info(f"Writing file: {safe_path} ({len(content)} bytes)")
            
            async with self.conn.start_sftp_client() as sftp:
                async with sftp.open(safe_path, 'w') as f:
                    await f.write(content)
            return f"Successfully wrote to {safe_path}"
        except (asyncssh.ConnectionLost, BrokenPipeError):
            if retry:
                self.conn = None
                await self._ensure_connection()
                return await self.write_file(path, content, retry=False)
            raise
