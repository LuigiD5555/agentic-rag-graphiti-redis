FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Create directories for models and work
RUN mkdir -p /models /work && chmod 777 /models /work

# Security: run as non-root user
RUN useradd -m -u 1000 tooluser && \
    chown -R tooluser:tooluser /app /models /work

USER tooluser

ENV PORT=8000
ENV WORK_DIR=/work
ENV MODELS_DIR=/models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import requests; requests.get('http://localhost:8000/healthz', timeout=2)" || exit 1

CMD ["python3", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
