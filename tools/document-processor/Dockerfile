FROM python:3.12-slim

# Install ALL document processing tools (OCR + Office + shared dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR tools
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    # Office conversion tools
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-core \
    # Java for LibreOffice
    default-jre-headless \
    # Shared dependencies (PDF utilities)
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (same for both OCR and Office)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy consolidated application
COPY src/ ./src/

# Create work directory
RUN mkdir -p /work && chmod 777 /work

# Security: run as non-root user
RUN useradd -m -u 1000 tooluser && \
    chown -R tooluser:tooluser /app /work

USER tooluser

ENV PORT=8000
ENV WORK_DIR=/tmp/rag-work
ENV HOME=/home/tooluser
ENV XDG_RUNTIME_DIR=/tmp/runtime-tooluser
ENV JAVALD_LIBRARY_PATH=/usr/lib/libreoffice/program

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/healthz', timeout=2)" || exit 1

# Initialize LibreOffice profile and create runtime directory
CMD mkdir -p /tmp/runtime-tooluser && chmod 700 /tmp/runtime-tooluser && \
    libreoffice --headless --terminate_after_init && \
    python -m uvicorn src.app:app --host 0.0.0.0 --port 8000
