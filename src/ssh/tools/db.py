"""Database query and schema inspection tools.

Supports: PostgreSQL (psql), MySQL/MariaDB (mysql), ScyllaDB/Cassandra (cqlsh), MongoDB (mongosh).
Database clients are executed inside Docker containers.

Features:
- Timeout protection (default: 60s)
- Read-only mode for safety
- Result limiting (default: 1000 rows)
- Execution metadata
- Structured error handling
"""
import logging
import re
import time
from typing import Any

from .base import docker_available

logger = logging.getLogger("ssh-mcp")


# Destructive keywords per database type
SQL_DESTRUCTIVE = {"INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "MERGE"}
CQL_DESTRUCTIVE = {"INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "BATCH"}
MONGO_DESTRUCTIVE = {
    "insertOne", "insertMany", "insert",
    "updateOne", "updateMany", "update", "replaceOne",
    "deleteOne", "deleteMany", "remove",
    "drop", "dropDatabase", "createCollection", "createIndex",
    "renameCollection", "bulkWrite"
}


def _is_destructive_query(query: str, db_type: str) -> bool:
    """Check if query contains destructive operations."""
    db_type = db_type.lower()
    
    if db_type in ("mongodb", "mongo"):
        # MongoDB: check for method names
        for keyword in MONGO_DESTRUCTIVE:
            if keyword in query:
                return True
        return False
    elif db_type in ("scylladb", "cassandra"):
        keywords = CQL_DESTRUCTIVE
    else:  # postgres, mysql
        keywords = SQL_DESTRUCTIVE
    
    # SQL/CQL: case-insensitive word boundary check
    query_upper = query.upper()
    for keyword in keywords:
        # Match whole word only
        if re.search(rf'\b{keyword}\b', query_upper):
            return True
    return False


def _add_limit_if_needed(query: str, db_type: str, max_rows: int) -> str:
    """Add LIMIT clause to SELECT queries if not present."""
    if max_rows is None:
        return query
    
    db_type = db_type.lower()
    query_upper = query.upper().strip()
    
    # Only add LIMIT to SELECT-like queries
    if db_type in ("mongodb", "mongo"):
        # MongoDB: add .limit() if not present
        if ".find(" in query and ".limit(" not in query:
            # Insert before final ) or at end
            if query.rstrip().endswith(")"):
                return query.rstrip()[:-1] + f").limit({max_rows})"
            else:
                return query + f".limit({max_rows})"
    else:
        # SQL/CQL: add LIMIT if SELECT and no LIMIT present
        if query_upper.startswith("SELECT") and "LIMIT" not in query_upper:
            return query.rstrip().rstrip(";") + f" LIMIT {max_rows};"
    
    return query


def _build_postgres_cmd(container: str, username: str, password: str, database: str | None, query: str, timeout: int) -> str:
    """Build PostgreSQL command with proper authentication."""
    db_flag = f"-d {database}" if database else ""
    base_cmd = f"PGPASSWORD='{password}' psql -U {username} {db_flag} -c '{query}'"
    return f"timeout {timeout} docker exec {container} sh -c \"{base_cmd}\" 2>&1"


def _build_mysql_cmd(container: str, username: str, password: str, database: str | None, query: str, timeout: int) -> str:
    """Build MySQL command with proper authentication."""
    db_flag = database if database else ""
    base_cmd = f"mysql -u {username} -p'{password}' {db_flag} -e '{query}'"
    return f"timeout {timeout} docker exec {container} {base_cmd} 2>&1"


def _build_cqlsh_cmd(container: str, username: str | None, password: str | None, query: str, timeout: int) -> str:
    """Build ScyllaDB/Cassandra cqlsh command with proper authentication."""
    auth_flags = ""
    if username:
        auth_flags += f" -u {username}"
    if password:
        auth_flags += f" -p '{password}'"
    return f"timeout {timeout} docker exec {container} cqlsh{auth_flags} -e '{query}' 2>&1"


def _build_mongo_cmd(container: str, username: str | None, password: str | None, database: str, query: str, timeout: int) -> str:
    """Build MongoDB mongosh command with proper authentication."""
    if username and password:
        auth = f"mongodb://{username}:{password}@localhost:27017/{database}?authSource=admin"
        return f"timeout {timeout} docker exec {container} mongosh '{auth}' --quiet --eval '{query}' 2>&1"
    else:
        return f"timeout {timeout} docker exec {container} mongosh {database} --quiet --eval '{query}' 2>&1"


def _parse_error(output: str, db_type: str) -> dict[str, Any] | None:
    """Parse database error from output into structured format."""
    output_lower = output.lower()
    
    # Check for common error patterns
    if "error" not in output_lower and "exception" not in output_lower and "failed" not in output_lower:
        return None
    
    error_info = {
        "error": output.strip(),
        "error_type": "unknown",
        "suggestion": None
    }
    
    # PostgreSQL errors
    if "relation" in output_lower and "does not exist" in output_lower:
        error_info["error_type"] = "table_not_found"
        error_info["suggestion"] = "Check table name or create the table first"
    elif "password authentication failed" in output_lower:
        error_info["error_type"] = "auth_failed"
        error_info["suggestion"] = "Check username and password"
    elif "connection refused" in output_lower:
        error_info["error_type"] = "connection_refused"
        error_info["suggestion"] = "Ensure database is running and accessible"
    elif "permission denied" in output_lower:
        error_info["error_type"] = "permission_denied"
        error_info["suggestion"] = "User lacks required permissions"
    elif "syntax error" in output_lower:
        error_info["error_type"] = "syntax_error"
        error_info["suggestion"] = "Check query syntax"
    elif "timeout" in output_lower or "timed out" in output_lower:
        error_info["error_type"] = "timeout"
        error_info["suggestion"] = "Query took too long, try with higher timeout or optimize query"
    
    return error_info


async def db_query(
    manager,
    container_name: str,
    db_type: str,
    query: str,
    database: str | None = None,
    username: str | None = None,
    password: str | None = None,
    target: str = "primary",
    timeout: int = 60,
    read_only: bool = False,
    max_rows: int | None = 1000,
) -> dict[str, Any]:
    """Execute a SQL/CQL/MongoDB query inside a database container.
    
    Args:
        container_name: Docker container name running the database
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        query: The query to execute (SQL, CQL, or MongoDB shell command)
        database: Database/keyspace name (required for postgres, mysql, mongodb)
        username: Database username (required for authenticated databases)
        password: Database password (required for authenticated databases)
        target: SSH connection alias
        timeout: Query timeout in seconds (default: 60)
        read_only: If True, reject destructive queries (INSERT, UPDATE, DELETE, etc.)
        max_rows: Limit result rows (default: 1000, None for unlimited)
        
    Returns:
        {
            "db_type": str,
            "query": str,
            "result": str,
            "metadata": {"execution_time_ms": int, "container": str},
            "error": str | None
        }
    """
    result = {
        "db_type": db_type,
        "query": query,
        "result": "",
        "metadata": {
            "container": container_name,
            "execution_time_ms": 0,
            "timeout": timeout,
            "read_only": read_only,
            "max_rows": max_rows
        },
        "error": None
    }
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    db_type_lower = db_type.lower()
    
    # Read-only check
    if read_only and _is_destructive_query(query, db_type_lower):
        result["error"] = f"Query rejected: read_only=True but query contains destructive operations"
        result["metadata"]["blocked_reason"] = "destructive_query"
        return result
    
    # Apply result limiting
    query = _add_limit_if_needed(query, db_type_lower, max_rows)
    result["query"] = query  # Update with potentially modified query
    
    # Escape single quotes in query for shell safety
    safe_query = query.replace("'", "'\\''")
    
    try:
        if db_type_lower == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, safe_query, timeout)
            
        elif db_type_lower == "mysql":
            if not username or not password:
                result["error"] = "MySQL requires username and password"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, safe_query, timeout)
            
        elif db_type_lower in ("scylladb", "cassandra"):
            cmd = _build_cqlsh_cmd(container_name, username, password, safe_query, timeout)
            
        elif db_type_lower in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            cmd = _build_mongo_cmd(container_name, username, password, database, safe_query, timeout)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}. Supported: postgres, mysql, scylladb, cassandra, mongodb"
            return result
        
        # Execute with timing
        start_time = time.time()
        logger.info(f"Executing DB query on {container_name} ({db_type_lower})")
        output = await manager.execute(cmd, target)
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        result["metadata"]["execution_time_ms"] = elapsed_ms
        
        # Check for errors in output
        error_info = _parse_error(output, db_type_lower)
        if error_info:
            result["error"] = error_info["error"]
            result["metadata"]["error_type"] = error_info["error_type"]
            if error_info["suggestion"]:
                result["metadata"]["suggestion"] = error_info["suggestion"]
        else:
            result["result"] = output
        
    except Exception as e:
        logger.error(f"DB query failed: {e}")
        result["error"] = str(e)
    
    return result


async def db_schema(
    manager,
    container_name: str,
    db_type: str,
    database: str | None = None,
    username: str | None = None,
    password: str | None = None,
    target: str = "primary",
    timeout: int = 30,
) -> dict[str, Any]:
    """Get database schema (tables/collections list).
    
    Args:
        container_name: Docker container name
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        database: Database/keyspace name
        username: Database username
        password: Database password
        timeout: Query timeout in seconds (default: 30)
        
    Returns:
        {"db_type": str, "container": str, "tables": str, "error": str | None}
    """
    result = {
        "db_type": db_type,
        "container": container_name,
        "tables": "",
        "error": None
    }
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    db_type_lower = db_type.lower()
    
    try:
        if db_type_lower == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, "\\dt", timeout)
            
        elif db_type_lower == "mysql":
            if not username or not password or not database:
                result["error"] = "MySQL requires username, password, and database"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, "SHOW TABLES;", timeout)
            
        elif db_type_lower in ("scylladb", "cassandra"):
            if database:
                auth_flags = ""
                if username:
                    auth_flags += f" -u {username}"
                if password:
                    auth_flags += f" -p '{password}'"
                cmd = f"timeout {timeout} docker exec {container_name} cqlsh{auth_flags} -k {database} -e 'DESCRIBE TABLES;' 2>&1"
            else:
                cmd = _build_cqlsh_cmd(container_name, username, password, "DESCRIBE KEYSPACES;", timeout)
                
        elif db_type_lower in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            cmd = _build_mongo_cmd(container_name, username, password, database, "db.getCollectionNames()", timeout)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            return result
            
        logger.info(f"Getting schema from {container_name} ({db_type_lower})")
        result["tables"] = await manager.execute(cmd, target)
        
    except Exception as e:
        logger.error(f"Schema fetch failed: {e}")
        result["error"] = str(e)
    
    return result


async def db_describe_table(
    manager,
    container_name: str,
    db_type: str,
    table: str,
    database: str | None = None,
    username: str | None = None,
    password: str | None = None,
    target: str = "primary",
    timeout: int = 30,
) -> dict[str, Any]:
    """Describe a specific table/collection structure.
    
    Args:
        container_name: Docker container name
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        table: Table/collection name
        database: Database/keyspace name
        username: Database username
        password: Database password
        timeout: Query timeout in seconds (default: 30)
        
    Returns:
        {"db_type": str, "table": str, "schema": str, "error": str | None}
    """
    result = {
        "db_type": db_type,
        "table": table,
        "schema": "",
        "error": None
    }
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    db_type_lower = db_type.lower()
    
    try:
        if db_type_lower == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, f"\\d {table}", timeout)
            
        elif db_type_lower == "mysql":
            if not username or not password or not database:
                result["error"] = "MySQL requires username, password, and database"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, f"DESCRIBE {table};", timeout)
            
        elif db_type_lower in ("scylladb", "cassandra"):
            if database:
                query = f"DESCRIBE TABLE {database}.{table};"
            else:
                query = f"DESCRIBE TABLE {table};"
            cmd = _build_cqlsh_cmd(container_name, username, password, query, timeout)
                
        elif db_type_lower in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            query = f"db.{table}.findOne()"
            cmd = _build_mongo_cmd(container_name, username, password, database, query, timeout)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            return result
            
        logger.info(f"Describing table {table} from {container_name} ({db_type_lower})")
        result["schema"] = await manager.execute(cmd, target)
        
    except Exception as e:
        logger.error(f"Describe table failed: {e}")
        result["error"] = str(e)
    
    return result


async def list_db_containers(manager, target: str = "primary") -> dict[str, Any]:
    """Find Docker containers that look like databases.
    
    Scans running containers and identifies database images.
    
    Returns:
        {"containers": [{"name": str, "image": str, "likely_type": str}], "error": str | None}
    """
    result = {"containers": [], "error": None}
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    cmd = "docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null"
    output = await manager.execute(cmd, target)
    
    db_keywords = {
        "postgres": "postgres",
        "mysql": "mysql",
        "mariadb": "mysql",
        "scylla": "scylladb",
        "cassandra": "cassandra",
        "mongo": "mongodb",
        "redis": "redis",
        "cockroach": "cockroachdb",
        "timescale": "timescaledb",
        "clickhouse": "clickhouse",
    }
    
    for line in output.strip().split("\n"):
        if "|" in line:
            name, image = line.split("|", 1)
            image_lower = image.lower()
            likely_type = None
            for keyword, db_type in db_keywords.items():
                if keyword in image_lower:
                    likely_type = db_type
                    break
            if likely_type:
                result["containers"].append({
                    "name": name,
                    "image": image,
                    "likely_type": likely_type
                })
    
    return result
