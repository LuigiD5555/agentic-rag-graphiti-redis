FROM python:3.11-slim

WORKDIR /app

# Install curl and ping for debugging / network tests
RUN apt-get update && apt-get install -y curl iputils-ping && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt --no-cache-dir -v
COPY src/ src/

EXPOSE 5000
CMD ["python", "-m", "src.main", "--socket"]
