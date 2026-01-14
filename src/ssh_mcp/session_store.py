import asyncio
import time
import logging
from typing import Dict, Optional, Any
from .ssh_manager import SSHManager

logger = logging.getLogger("ssh-mcp-sessions")

class SessionEntry:
    def __init__(self, manager: SSHManager):
        self.manager = manager
        self.last_accessed = time.time()

    def touch(self):
        self.last_accessed = time.time()

class SessionStore:
    def __init__(self, timeout_seconds: int = 300):
        self._sessions: Dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()
        self._timeout = timeout_seconds
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._next_sleep: float = 30.0  # Adaptive sleep interval

    async def start(self):
        """Start the background cleanup task."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"SessionStore started (Timeout: {self._timeout}s)")

    async def stop(self):
        """Stop the cleanup task and close all sessions."""
        async with self._lock:
            if not self._running:
                return
            self._running = False
            
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all active connections
        async with self._lock:
            count = len(self._sessions)
            for key, entry in self._sessions.items():
                await entry.manager.disconnect()
            self._sessions.clear()
        logger.info(f"SessionStore stopped and cleared ({count} sessions closed).")

    async def get(self, key: str) -> SSHManager:
        """Get an existing session or create a new one.
        
        Uses double-checked locking for better parallel throughput:
        - Fast path: Existing sessions don't need lock
        - Slow path: New sessions acquire lock briefly
        """
        # Fast path: Check without lock (read is atomic for dict.get)
        entry = self._sessions.get(key)
        if entry:
            entry.touch()
            logger.debug(f"Reusing session for key: {key} (fast path)")
            return entry.manager
        
        # Slow path: Create new session with lock
        async with self._lock:
            # Double-check after acquiring lock (another task may have created it)
            entry = self._sessions.get(key)
            if entry:
                entry.touch()
                logger.debug(f"Reusing session for key: {key} (slow path)")
                return entry.manager
            
            # Create new
            logger.info(f"Creating new session for key: {key}")
            manager = SSHManager()
            self._sessions[key] = SessionEntry(manager)
            return manager

    async def _cleanup_loop(self):
        """Background loop to reap idle sessions with adaptive interval."""
        while self._running:
            try:
                await asyncio.sleep(self._next_sleep)
                await self._reap()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _reap(self):
        """Remove sessions older than the timeout. Calculates optimal next check interval."""
        now = time.time()
        to_remove = []
        next_expiry = float('inf')
        
        # First pass: identify expired sessions and calculate next expiry
        async with self._lock:
            for key, entry in self._sessions.items():
                age = now - entry.last_accessed
                if age > self._timeout:
                    to_remove.append(key)
                else:
                    # Time until this session expires
                    time_until_expiry = self._timeout - age
                    next_expiry = min(next_expiry, time_until_expiry)
        
        # Remove expired sessions (with disconnect outside main lock)
        for key in to_remove:
            logger.info(f"Cleaning up idle session: {key}")
            manager = None
            async with self._lock:
                if key in self._sessions:
                    # Double check timestamp inside lock
                    if (now - self._sessions[key].last_accessed) > self._timeout:
                        entry = self._sessions.pop(key)
                        manager = entry.manager
            
            if manager:
                try:
                    await manager.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting idle session {key}: {e}")
        
        # Calculate adaptive sleep interval
        if next_expiry == float('inf'):
            # No sessions, sleep longer
            self._next_sleep = 60.0
        else:
            # Sleep until just after next expiry (with bounds)
            self._next_sleep = max(5.0, min(next_expiry + 1.0, 60.0))
        
        logger.debug(f"Next cleanup in {self._next_sleep:.1f}s ({len(self._sessions)} active sessions)")

