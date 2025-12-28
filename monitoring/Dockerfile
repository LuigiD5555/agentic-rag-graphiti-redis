# Monitoring Container for RAG Agentic Graphiti
# Handles log analysis, diagnostics, and volume monitoring

FROM python:3.11-slim

LABEL maintainer="RAG Project Monitoring"
LABEL description="Monitoring, diagnostics, and log analysis container"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    systemd \
    curl \
    wget \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY monitoring/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy monitoring scripts and utilities
COPY monitoring/src/ ./src/
COPY monitoring/scripts/ ./scripts/
COPY monitoring/config/ ./config/

# Copy shared utilities from main project (if needed)
COPY src/utils/volume_monitor.py ./src/utils/
COPY src/utils/volume_watcher.py ./src/utils/

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
COPY monitoring/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["daemon"]