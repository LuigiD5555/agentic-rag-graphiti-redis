FROM docker.io/nvidia/cuda:12.2.0-base-ubuntu22.04

# Install system Python and pip (Ubuntu 22.04 ships Python 3.10)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Create work directory
RUN mkdir -p /work && chmod 777 /work

# Security: run as non-root user (but keep GPU access)
RUN useradd -m -u 1000 tooluser && \
    chown -R tooluser:tooluser /app /work

USER tooluser

ENV PORT=8000
ENV WORK_DIR=/work

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:8000/healthz', timeout=2)" || exit 1

CMD ["python3", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
