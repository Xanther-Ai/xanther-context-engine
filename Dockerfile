FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY xce/ xce/

# Install Python dependencies
RUN pip install --no-cache-dir .

# Expose MCP server port
EXPOSE 8000

# Run MCP server in SSE mode
CMD ["python", "-m", "xce.mcp_server", "--sse"]
