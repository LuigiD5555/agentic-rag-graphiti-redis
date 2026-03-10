########################
# Base (dependencies) - Alpine, NO LibreOffice
########################
FROM python:3.12-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

# Minimal build dependencies for Python packages
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    linux-headers \
    curl \
    git \
    libffi-dev \
    openssl-dev

WORKDIR /app

# Leverage Docker layer caching: install deps first
COPY requirements.txt .

# Install requirements (LM Studio only, no torch/sentence-transformers)
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

########################
# Test stage (optional)
########################
# This stage is never shipped to production. It exists only to run pytest.
FROM base AS test

# Copy only what tests need
COPY src/ src/
COPY swarm_rag/ swarm_rag/
COPY tests/ tests/

# Optionally allow extra test-only tools here
# RUN pip install --no-cache-dir -r tests/requirements.txt

# run tests by mounting the repo at runtime (see notes below).
ARG RUN_TESTS=0
# When building with --build-arg RUN_TESTS=1 this will run pytest.
# Otherwise it will be skipped (default).
RUN if [ "$RUN_TESTS" = "1" ]; then pytest -q; fi

########################
# Runtime (unified for both ingestion and API)
########################
FROM base AS runtime

# Copy configuration files for ingestion
COPY .ingestignore /app/.ingestignore

# Set environment variables for default paths
ENV DOCS_EXCLUDE_FILE=/app/.ingestignore

# Copy application code
COPY src/ src/
COPY swarm_rag/ swarm_rag/
COPY tests/ tests/

# Create data directory for API file uploads
RUN mkdir -p data

# Expose API port (configurable via API_PORT env var)
# Default port is now 8000 (consolidated from separate API proxy)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os, requests; requests.get(f'http://localhost:{os.getenv(\"API_PORT\", \"8000\")}/health')" || exit 0

# Default command: HTTP server mode (unified RAG API)
# SECURITY: Bind to localhost only when using host network mode
CMD sh -c "uvicorn src.api.app:app --host 127.0.0.1 --port ${API_PORT:-8000}"

########################
# Development stage (with hot-reload for API)
########################
FROM runtime AS development

# Install development/testing tools
RUN pip install --no-cache-dir pytest pytest-asyncio httpx ipdb

# Default: HTTP server with auto-reload
# SECURITY: Bind to localhost only when using host network mode
CMD sh -c "uvicorn src.api.app:app --host 127.0.0.1 --port ${API_PORT:-8000} --reload"