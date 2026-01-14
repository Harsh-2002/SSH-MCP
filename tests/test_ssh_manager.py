import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
from ssh_mcp.ssh_manager import SSHManager

class TestSSHManager(unittest.IsolatedAsyncioTestCase):
    async def test_connect(self):
        manager = SSHManager()
        
        # Mock the connection object
        mock_conn = AsyncMock()
        mock_conn.run.return_value = MagicMock(stdout="/home/user", stderr="", exit_status=0)
        
        # Mock asyncssh.connect
        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_conn
            
            result = await manager.connect("localhost", "user", password="password")
            
            self.assertIn("Connected to", result)
            self.assertEqual(manager.cwd, "/home/user")
            mock_connect.assert_called_with(
                "localhost", 
                port=22, 
                username="user", 
                password="password", 
                client_keys=None,
                known_hosts=None
            )

    async def test_execute_cwd_tracking(self):
        manager = SSHManager()
        manager.conn = AsyncMock()
        manager.cwd = "/current"
        
        # Simulate execution
        # Expected output from the wrapper logic:
        # User output
        # ___MCP_CWD_CAPTURE___
        # /new/path
        
        mock_result = MagicMock()
        mock_result.stdout = "User Output\n___MCP_CWD_CAPTURE___\n/new/path\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0
        
        manager.conn.run.return_value = mock_result
        
        output = await manager.execute("cd /new/path && ls")
        
        # Verify CWD updated
        self.assertEqual(manager.cwd, "/new/path")
        
        # Verify output is clean (no delimiter)
        self.assertIn("User Output", output)
        self.assertNotIn("___MCP_CWD_CAPTURE___", output)

    async def test_execute_truncation(self):
        manager = SSHManager()
        manager.conn = AsyncMock()
        
        long_output = "a" * 5000 + "\n___MCP_CWD_CAPTURE___\n/same/path"
        
        mock_result = MagicMock()
        mock_result.stdout = long_output
        mock_result.stderr = ""
        mock_result.exit_status = 0
        
        manager.conn.run.return_value = mock_result
        
        output = await manager.execute("cat bigfile")
        
        self.assertTrue(len(output) < 4200)
        self.assertIn("truncated", output)

if __name__ == "__main__":
    unittest.main()
