"""Database query and schema inspection tools.

Supports: PostgreSQL (psql), ScyllaDB/Cassandra (cqlsh), MySQL/MariaDB (mysql).
Database clients are executed inside Docker containers.
"""
import logging
from typing import Any

from .base import docker_available

logger = logging.getLogger("ssh-mcp")


async def db_schema(manager, container_name: str, db_type: str,
                    database: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Get database schema (tables, columns) by executing CLI inside a container.
    
    Args:
        container_name: Name of the Docker container running the database.
        db_type: One of "postgres", "mysql", "scylladb".
        database: Database name (required for postgres/mysql, optional for scylladb).
        
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
            db_flag = f"-d {database}" if database else ""
            # List tables
            tables_cmd = f"docker exec {container_name} psql -U postgres {db_flag} -c '\\dt' 2>&1"
            result["tables"] = await manager.run_command(tables_cmd, target)
            
        elif db_type == "mysql":
            if not database:
                result["error"] = "Database name is required for MySQL"
                return result
            # List tables
            tables_cmd = f"docker exec {container_name} mysql -u root {database} -e 'SHOW TABLES;' 2>&1"
            result["tables"] = await manager.run_command(tables_cmd, target)
            
        elif db_type in ("scylladb", "cassandra"):
            # List keyspaces and tables
            keyspace = database or ""
            if keyspace:
                tables_cmd = f"docker exec {container_name} cqlsh -e 'DESCRIBE TABLES;' {keyspace} 2>&1"
            else:
                tables_cmd = f"docker exec {container_name} cqlsh -e 'DESCRIBE KEYSPACES;' 2>&1"
            result["tables"] = await manager.run_command(tables_cmd, target)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}. Use postgres, mysql, or scylladb."
            
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def db_describe_table(manager, container_name: str, db_type: str,
                            table: str, database: str | None = None, 
                            target: str = "primary") -> dict[str, Any]:
    """Describe a specific table's structure.
    
    Args:
        container_name: Name of the Docker container.
        db_type: One of "postgres", "mysql", "scylladb".
        table: Table name to describe.
        database: Database/keyspace name.
        
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
            db_flag = f"-d {database}" if database else ""
            cmd = f"docker exec {container_name} psql -U postgres {db_flag} -c '\\d {table}' 2>&1"
            result["schema"] = await manager.run_command(cmd, target)
            
        elif db_type == "mysql":
            if not database:
                result["error"] = "Database name is required for MySQL"
                return result
            cmd = f"docker exec {container_name} mysql -u root {database} -e 'DESCRIBE {table};' 2>&1"
            result["schema"] = await manager.run_command(cmd, target)
            
        elif db_type in ("scylladb", "cassandra"):
            keyspace = database or ""
            if keyspace:
                cmd = f"docker exec {container_name} cqlsh -e 'DESCRIBE TABLE {keyspace}.{table};' 2>&1"
            else:
                cmd = f"docker exec {container_name} cqlsh -e 'DESCRIBE TABLE {table};' 2>&1"
            result["schema"] = await manager.run_command(cmd, target)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def db_query(manager, container_name: str, db_type: str, query: str,
                   database: str | None = None, target: str = "primary") -> dict[str, Any]:
    """Execute a SQL/CQL query inside a database container.
    
    Args:
        container_name: Name of the Docker container.
        db_type: One of "postgres", "mysql", "scylladb".
        query: The SQL/CQL query to execute.
        database: Database/keyspace name.
        
    Returns:
        {"db_type": str, "query": str, "result": str, "error": str | None}
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
    
    # Escape single quotes in query for shell
    safe_query = query.replace("'", "'\\''")
    
    try:
        if db_type == "postgres":
            db_flag = f"-d {database}" if database else ""
            cmd = f"docker exec {container_name} psql -U postgres {db_flag} -c '{safe_query}' 2>&1"
            result["result"] = await manager.run_command(cmd, target)
            
        elif db_type == "mysql":
            db_flag = database if database else ""
            cmd = f"docker exec {container_name} mysql -u root {db_flag} -e '{safe_query}' 2>&1"
            result["result"] = await manager.run_command(cmd, target)
            
        elif db_type in ("scylladb", "cassandra"):
            cmd = f"docker exec {container_name} cqlsh -e '{safe_query}' 2>&1"
            result["result"] = await manager.run_command(cmd, target)
            
        else:
            result["error"] = f"Unsupported db_type: {db_type}"
            
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def list_db_containers(manager, target: str = "primary") -> dict[str, Any]:
    """Find Docker containers that look like databases.
    
    Returns:
        {"containers": [{"name": str, "image": str, "likely_type": str}]}
    """
    result = {"containers": [], "error": None}
    
    if not await docker_available(manager, target):
        result["error"] = "Docker is not available on target"
        return result
    
    # Get all containers with their images
    cmd = "docker ps --format '{{.Names}}|{{.Image}}' 2>/dev/null"
    output = await manager.run_command(cmd, target)
    
    db_keywords = {
        "postgres": "postgres",
        "mysql": "mysql",
        "mariadb": "mysql",
        "scylla": "scylladb",
        "cassandra": "scylladb",
        "mongo": "mongodb",
        "redis": "redis",
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
