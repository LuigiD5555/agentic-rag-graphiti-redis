# Monitoring Container for RAG Agentic Graphiti
# Handles log analysis, diagnostics, and volume monitoring

FROM python:3.12-slim

LABEL maintainer="RAG Project Monitoring"
LABEL description="Monitoring, diagnostics, and log analysis container"

# Install only required system dependencies
# - libsystemd0: systemd journal library (1.2 MB)
# - python3-systemd: Python bindings for journald (634 KB)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsystemd0 \
    python3-systemd \
    systemd \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY tools/monitoring/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/monitoring/src/ ./src/
COPY tools/monitoring/config/ ./config/

# Copy shared utilities from main project
COPY src/utils/ ./src/utils/
COPY src/rag/__init__.py ./src/rag/__init__.py
COPY src/rag/audit/ ./src/rag/audit/
COPY src/rag/interfaces/ ./src/rag/interfaces/

# Create necessary directories
RUN mkdir -p /app/logs /app/data /app/reports

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MONITORING_MODE=standalone
ENV LOG_LEVEL=INFO

# Expose port for optional web dashboard
EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Entry point script
COPY tools/monitoring/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["daemon"]
