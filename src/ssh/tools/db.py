"""Database query and schema inspection tools.

Supports: PostgreSQL (psql), MySQL/MariaDB (mysql), ScyllaDB/Cassandra (cqlsh), MongoDB (mongosh).
Database clients are executed inside Docker containers.

IMPORTANT: All authentication is explicit - no default usernames or passwords.
Users must always provide credentials.
"""
import logging
from typing import Any

from .base import docker_available

logger = logging.getLogger("ssh-mcp")


def _build_postgres_cmd(container: str, username: str, password: str, database: str | None, query: str) -> str:
    """Build PostgreSQL command with proper authentication."""
    db_flag = f"-d {database}" if database else ""
    # Use PGPASSWORD env var for password (secure, doesn't appear in ps)
    return f"docker exec {container} sh -c \"PGPASSWORD='{password}' psql -U {username} {db_flag} -c '{query}'\" 2>&1"


def _build_mysql_cmd(container: str, username: str, password: str, database: str | None, query: str) -> str:
    """Build MySQL command with proper authentication."""
    db_flag = database if database else ""
    # Password passed via -p flag
    return f"docker exec {container} mysql -u {username} -p'{password}' {db_flag} -e '{query}' 2>&1"


def _build_cqlsh_cmd(container: str, username: str | None, password: str | None, query: str) -> str:
    """Build ScyllaDB/Cassandra cqlsh command with proper authentication."""
    auth_flags = ""
    if username:
        auth_flags += f" -u {username}"
    if password:
        auth_flags += f" -p '{password}'"
    return f"docker exec {container} cqlsh{auth_flags} -e '{query}' 2>&1"


def _build_mongo_cmd(container: str, username: str | None, password: str | None, database: str, query: str) -> str:
    """Build MongoDB mongosh command with proper authentication."""
    if username and password:
        # Use connection string with auth
        auth = f"mongodb://{username}:{password}@localhost:27017/{database}?authSource=admin"
        return f"docker exec {container} mongosh '{auth}' --quiet --eval '{query}' 2>&1"
    else:
        # No auth
        return f"docker exec {container} mongosh {database} --quiet --eval '{query}' 2>&1"


async def db_query(manager, container_name: str, db_type: str, query: str,
                   database: str | None = None, username: str | None = None,
                   password: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Execute a SQL/CQL/MongoDB query inside a database container.
    
    Args:
        container_name: Docker container name running the database
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        query: The query to execute (SQL, CQL, or MongoDB shell command)
        database: Database/keyspace name (required for postgres, mysql, mongodb)
        username: Database username (required for authenticated databases)
        password: Database password (required for authenticated databases)
        target: SSH connection alias
        
    Returns:
        {"db_type": str, "query": str, "result": str, "error": str | None}
        
    Examples:
        PostgreSQL: db_query("pg-container", "postgres", "SELECT * FROM users;", "mydb", "admin", "secret")
        MySQL: db_query("mysql-container", "mysql", "SHOW TABLES;", "mydb", "root", "password")
        ScyllaDB: db_query("scylla-container", "scylladb", "SELECT * FROM keyspace.table;", None, "user", "pass")
        MongoDB: db_query("mongo-container", "mongodb", "db.users.find().limit(5)", "mydb", "admin", "secret")
    """
    result = {
        "db_type": db_type,
        "query": query,
        "result": "",
        "error": None
    }
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    db_type = db_type.lower()
    
    # Escape single quotes in query for shell safety
    safe_query = query.replace("'", "'\\''")
    
    try:
        if db_type == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, safe_query)
            
        elif db_type == "mysql":
            if not username or not password:
                result["error"] = "MySQL requires username and password"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, safe_query)
            
        elif db_type in ("scylladb", "cassandra"):
            # ScyllaDB/Cassandra may or may not require auth depending on config
            cmd = _build_cqlsh_cmd(container_name, username, password, safe_query)
            
        elif db_type in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            cmd = _build_mongo_cmd(container_name, username, password, database, safe_query)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}. Supported: postgres, mysql, scylladb, cassandra, mongodb"
            return result
            
        logger.info(f"Executing DB query on {container_name} ({db_type})")
        result["result"] = await manager.execute(cmd, target)
        
    except Exception as e:
        logger.error(f"DB query failed: {e}")
        result["error"] = str(e)
    
    return result


async def db_schema(manager, container_name: str, db_type: str,
                    database: str | None = None, username: str | None = None,
                    password: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Get database schema (tables/collections list).
    
    Args:
        container_name: Docker container name
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        database: Database/keyspace name
        username: Database username
        password: Database password
        
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
    
    db_type = db_type.lower()
    
    try:
        if db_type == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, "\\dt")
            
        elif db_type == "mysql":
            if not username or not password or not database:
                result["error"] = "MySQL requires username, password, and database"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, "SHOW TABLES;")
            
        elif db_type in ("scylladb", "cassandra"):
            if database:
                query = f"DESCRIBE TABLES;"
                # Need to use keyspace in the command
                auth_flags = ""
                if username:
                    auth_flags += f" -u {username}"
                if password:
                    auth_flags += f" -p '{password}'"
                cmd = f"docker exec {container_name} cqlsh{auth_flags} -k {database} -e '{query}' 2>&1"
            else:
                query = "DESCRIBE KEYSPACES;"
                cmd = _build_cqlsh_cmd(container_name, username, password, query)
                
        elif db_type in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            cmd = _build_mongo_cmd(container_name, username, password, database, "db.getCollectionNames()")
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            return result
            
        logger.info(f"Getting schema from {container_name} ({db_type})")
        result["tables"] = await manager.execute(cmd, target)
        
    except Exception as e:
        logger.error(f"Schema fetch failed: {e}")
        result["error"] = str(e)
    
    return result


async def db_describe_table(manager, container_name: str, db_type: str,
                            table: str, database: str | None = None,
                            username: str | None = None, password: str | None = None,
                            target: str = "primary") -> dict[str, Any]:
    """Describe a specific table/collection structure.
    
    Args:
        container_name: Docker container name
        db_type: "postgres", "mysql", "scylladb", "cassandra", or "mongodb"
        table: Table/collection name
        database: Database/keyspace name
        username: Database username
        password: Database password
        
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
    
    db_type = db_type.lower()
    
    try:
        if db_type == "postgres":
            if not username or not password:
                result["error"] = "PostgreSQL requires username and password"
                return result
            cmd = _build_postgres_cmd(container_name, username, password, database, f"\\d {table}")
            
        elif db_type == "mysql":
            if not username or not password or not database:
                result["error"] = "MySQL requires username, password, and database"
                return result
            cmd = _build_mysql_cmd(container_name, username, password, database, f"DESCRIBE {table};")
            
        elif db_type in ("scylladb", "cassandra"):
            if database:
                query = f"DESCRIBE TABLE {database}.{table};"
            else:
                query = f"DESCRIBE TABLE {table};"
            cmd = _build_cqlsh_cmd(container_name, username, password, query)
                
        elif db_type in ("mongodb", "mongo"):
            if not database:
                result["error"] = "MongoDB requires a database name"
                return result
            # Get sample document and indexes to understand structure
            query = f"db.{table}.findOne()"
            cmd = _build_mongo_cmd(container_name, username, password, database, query)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            return result
            
        logger.info(f"Describing table {table} from {container_name} ({db_type})")
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
    
    # Get all containers with their images
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
