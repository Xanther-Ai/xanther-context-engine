FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for building the frontend
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY xce/ xce/

# Install Python dependencies
RUN pip install --no-cache-dir .

# Install UI dependencies and build
COPY xce/dashboard/ui/package.json xce/dashboard/ui/package.json
COPY xce/dashboard/ui/tsconfig.json xce/dashboard/ui/tsconfig.json
COPY xce/dashboard/ui/tsconfig.node.json xce/dashboard/ui/tsconfig.node.json
COPY xce/dashboard/ui/vite.config.ts xce/dashboard/ui/vite.config.ts
COPY xce/dashboard/ui/index.html xce/dashboard/ui/index.html
COPY xce/dashboard/ui/main.tsx xce/dashboard/ui/main.tsx
COPY xce/dashboard/ui/App.tsx xce/dashboard/ui/App.tsx
COPY xce/dashboard/ui/vite-env.d.ts xce/dashboard/ui/vite-env.d.ts
COPY xce/dashboard/ui/components xce/dashboard/ui/components
COPY xce/dashboard/ui/hooks xce/dashboard/ui/hooks
COPY xce/dashboard/ui/styles xce/dashboard/ui/styles
COPY xce/dashboard/ui/types xce/dashboard/ui/types

WORKDIR /app/xce/dashboard/ui
RUN npm install --legacy-peer-deps && npm run build
WORKDIR /app

# Create static directory for built UI
RUN mkdir -p static && mv xce/dashboard/ui/dist/* static/ 2>/dev/null || true

# Expose ports
EXPOSE 8000 8080

# Default: run MCP server in background, then dashboard
CMD sh -c "python -m xce.mcp_server --host 0.0.0.0 --port 8000 & python -m xce.dashboard.server --host 0.0.0.0 --port 8080 & wait"