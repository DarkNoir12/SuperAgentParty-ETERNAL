FROM python:3.12-slim

# 1. Install system dependencies and Node.js (includes npm)
RUN apt-get update && \
    # Install base tools and CA certificates (required for curl with https)
    apt-get install -y gcc curl git ca-certificates && \
    # Fetch and execute the NodeSource setup script for Node 20.x
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    # Install nodejs (apt install nodejs automatically includes npm)
    apt-get install -y nodejs && \
    # Clean APT cache to reduce image size
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy only dependency files first (to leverage caching)
COPY pyproject.toml uv.lock ./

# 3. Install Python dependencies
RUN pip install uv && \
    uv venv && \
    uv sync

# 4. Copy source code last (so code changes won't trigger dependency reinstallation)
COPY . .

# 5. Set permissions and create directories
RUN mkdir -p uploaded_files && \
    chmod 755 uploaded_files

EXPOSE 3456

# 6. Configure environment variables
# Remove ELECTRON_NODE_EXEC, add IS_DOCKER=1 so the Python backend knows it's running in Docker
ENV HOST=0.0.0.0 \
    PORT=3456 \
    PYTHONUNBUFFERED=1 \
    IS_DOCKER=1

CMD [".venv/bin/python", "server.py", "--host", "0.0.0.0", "--port", "3456"]
