# 🚀 Quick Start - REST API

A quick guide to start the Ollama-like REST API in minutes.

---

## 📋 Prerequisites

**Python 3.12** (to stay consistent with the rest of the project)

Make sure you have these running:

1. **Weaviate** (vector store) - Port 8080
2. **Neo4j** (graph store) - Port 7687
3. **Redis** (cache) - Port 6379
4. **LM Studio** (LLM) - Port 1234 with a model loaded

### Start services with Docker/Podman Compose

```bash
# API + all services (with auto-reload for development)
docker-compose -f docker-compose.api.yml up

# Or services only (no API)
podman-compose up -d
```

---

## ⚡ Quick Start (3 steps)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the API

```bash
# Local development (with auto-reload)
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# Or with Docker/Podman (includes all services)
docker-compose -f docker-compose.api.yml up
```

### 3. Test the API

```bash
# In another terminal
python tests/integration/test_api.py
```

---

## 🎯 Verify it works

### 1. Health Check

```bash
curl http://localhost:8000/health
```

You should see:
```json
{
  "status": "healthy",
  "rag_initialized": true,
  "embedding_initialized": true
}
```

### 2. List models

```bash
curl http://localhost:8000/api/tags | jq
```

### 3. First query

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-default",
    "messages": [
      {"role": "user", "content": "Hello, can you explain what you do?"}
    ],
    "options": {"temperature": 0.7, "max_tokens": 256, "top_k": 5}
  }' | jq
```

---

## 📚 Interactive documentation

Once the API is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

From there you can try all endpoints interactively.

---

## 💻 Example Requests

### Generate

```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-default",
    "prompt": "Explain neural networks",
    "options": {"temperature": 0.7, "max_tokens": 256}
  }' | jq
```

### RAG Query

```bash
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the main topics?",
    "top_k": 3
  }' | jq
```

---

## 🔧 Configuration

### Important environment variables

Create/edit `.env`:

```bash
# Vector Store
WEAVIATE_URL=http://localhost:8080
WEAVIATE_GRPC_PORT=50051
WEAVIATE_CLASS=RAGDocument
WEAVIATE_MULTI_TENANCY=true
WEAVIATE_DEFAULT_TENANT=tenant-default

# Graph Store
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# Cache
REDIS_HOST=localhost
REDIS_PORT=6379

# LM Studio (LLM)
LMSTUDIO_HOST=localhost
LMSTUDIO_PORT=1234
PROVIDER=lmstudio
```

---

## 🐛 Troubleshooting

### Error: "RAG orchestrator not initialized"

**Cause**: Services are not running or are not reachable.

**Solution**:
1. Verify Weaviate, Redis, Neo4j, and LM Studio are running
2. Check the API logs: `uvicorn src.api.app:app --log-level debug`
3. Test individual connections:

```bash
# Weaviate
curl http://localhost:8080/v1/.well-known/ready

# Redis
redis-cli ping

# Neo4j
curl http://localhost:7474

# LM Studio
curl http://localhost:1234/v1/models
```

### Error: "Connection refused"

**Cause**: The API is not running.

**Solution**:
```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### Error: "No module named 'fastapi'"

**Cause**: Dependencies are not installed.

**Solution**:
```bash
pip install -r requirements.txt
```

### Timeout on long responses

**Cause**: The RAG is processing many documents.

**Solution**: Reduce `top_k` in your requests:

```json
{
  "model": "rag-default",
  "messages": [...],
  "options": {"top_k": 3}
}
```

---

## 📊 Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/tags` | GET | List models |
| `/api/chat` | POST | Chat (Ollama-like) |
| `/api/generate` | POST | Generate (Ollama-like) |
| `/api/embeddings` | POST | Generate embeddings |
| `/rag/ingest` | POST | Ingest files |
| `/rag/query` | POST | RAG query |
| `/docs` | GET | Swagger UI |
| `/redoc` | GET | ReDoc |

---

## 🚢 Docker Compose Usage

### Using Docker Compose (recommended)

```bash
# Build and start
docker-compose -f docker-compose.api.yml up -d

# View logs
docker-compose -f docker-compose.api.yml logs -f app

# Restart
docker-compose -f docker-compose.api.yml restart app

# Stop
docker-compose -f docker-compose.api.yml down
```

### Manual Docker Build

```bash
# Build development stage
docker build -f Dockerfile --target development -t rag-app:dev .

# Run
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name rag-app \
  -v $(pwd)/src:/app/src:ro \
  rag-app:dev
```

**Note**: Changes in `src/` will be reflected automatically when using volume mounts.

---

## 📖 More Resources

- **Full documentation**: [src/api/README.md](src/api/README.md)
- **Tests**: `python tests/integration/test_api.py`

---

## 🎉 Next steps

1. **Ingest documents**: Before querying, ingest your documents
   ```bash
   python -m src.ingestion.cli /path/to/docs
   ```

2. **Explore the interactive docs**: http://localhost:8000/docs

3. **Integrate into your app**: Use `/api/*` and `/rag/*` endpoints

4. **Configure authentication**: Add API keys if you need them (see README)

---

## 💡 Tips

- **Port in use**: Change the port: `uvicorn src.api.app:app --port 8001`
- **Auto-reload**: Already included with `--reload` for local development
- **CORS**: Already configured to allow all origins
- **Logs**: Use `--log-level debug` for more detail

---

Done! Your RAG is now exposed as an Ollama-like API 🎉
