########################
# Base (dependencies)
########################
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System packages kept minimal; add only what you need
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Leverage Docker layer caching: install deps first
COPY requirements.txt .
COPY requirements-local-gpu.txt .
ARG INSTALL_LOCAL_GPU_DEPS=0
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && if [ "$INSTALL_LOCAL_GPU_DEPS" = "1" ]; then pip install --no-cache-dir -r requirements-local-gpu.txt; fi

########################
# Test stage (optional)
########################
# This stage is never shipped to production. It exists only to run pytest.
FROM base AS test

# Copy only what tests need
COPY src/ src/
COPY tests/ tests/

# Optionally allow extra test-only tools here
# RUN pip install --no-cache-dir -r tests/requirements.txt

# run tests by mounting the repo at runtime (see notes below).
ARG RUN_TESTS=0
# When building with --build-arg RUN_TESTS=1 this will run pytest.
# Otherwise it will be skipped (default).
RUN if [ "$RUN_TESTS" = "1" ]; then pytest -q; fi

########################
# Runtime (production)
########################
FROM base AS runtime

# Copy configuration files for ingestion
COPY .ingestignore /app/.ingestignore
COPY .enabledpaths /app/.enabledpaths

# Set environment variables for default paths
ENV DOCS_EXCLUDE_FILE=/app/.ingestignore
ENV DOCS_ENABLED_PATHS_FILE=/app/.enabledpaths

# Copy only the application code required at runtime
COPY src/ src/

# Default command
CMD ["python", "-m", "src.main"]
