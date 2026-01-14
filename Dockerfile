# Use official Python runtime
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Set work directory
WORKDIR /app

# Copy source code and config
COPY pyproject.toml README.md /app/
COPY src /app/src

# Install dependencies and package
RUN pip install --no-cache-dir .

# Create a non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app

# Create data directory for keys (Standard Persistence Location)
RUN mkdir -p /data && chown -R appuser:appuser /data && chmod 700 /data

USER appuser

# Expose the port
EXPOSE $PORT

# Run Streamable HTTP server (/mcp)
CMD ["uvicorn", "ssh_mcp.server_all:app", "--host", "0.0.0.0", "--port", "8000"]
