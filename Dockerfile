FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY podman-compose.yml podman-compose.yml
COPY src/ src/
COPY tests/ tests/

ARG RUN_TESTS=1
RUN if [ "$RUN_TESTS" = "1" ]; then pytest -q; fi

CMD ["python", "-m", "src.main"]
