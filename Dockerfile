########################
# Base (dependencies)
########################
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System packages kept minimal; add only what you need
# LibreOffice is required for processing .doc/.docx files via unstructured
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    libreoffice-writer \
    libreoffice-calc \
 && rm -rf /var/lib/apt/lists/*

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

# Set environment variables for default paths
ENV DOCS_EXCLUDE_FILE=/app/.ingestignore

# Copy only the application code required at runtime
COPY src/ src/

# Default command
CMD ["python", "-m", "src.main"]
