# 🚀 Quick Start - REST API

A quick guide to start the OpenAI-compatible REST API in minutes.

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
python tests/test_api.py
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
curl http://localhost:8000/v1/models | jq
```

### 3. First query

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-local",
    "messages": [
      {"role": "user", "content": "Hello, can you explain what you do?"}
    ]
  }' | jq
```

---

## 📚 Interactive documentation

Once the API is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

From there you can try all endpoints interactively.

---

## 💻 Use with the OpenAI SDK

### Python

```bash
pip install openai
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="rag-local",
    messages=[
        {"role": "user", "content": "What is machine learning?"}
    ]
)

print(response.choices[0].message.content)
```

### JavaScript/TypeScript

```bash
npm install openai
```

```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'not-needed',
});

const response = await client.chat.completions.create({
  model: 'rag-local',
  messages: [
    { role: 'user', content: 'What is machine learning?' }
  ],
});

console.log(response.choices[0].message.content);
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

```python
response = client.chat.completions.create(
    model="rag-local",
    messages=[...],
    top_k=3  # Instead of the default (5)
)
```

---

## 📊 Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/models` | GET | List models |
| `/v1/chat/completions` | POST | Chat (OpenAI legacy) |
| `/v1/responses` | POST | Responses (modern) |
| `/v1/embeddings` | POST | Generate embeddings |
| `/docs` | GET | Swagger UI |
| `/redoc` | GET | ReDoc |

---

## 🚢 Docker Compose Usage

### Using Docker Compose (recommended)

```bash
# Build and start
docker-compose -f docker-compose.api.yml up -d

# View logs
docker-compose -f docker-compose.api.yml logs -f rag-api

# Restart
docker-compose -f docker-compose.api.yml restart rag-api

# Stop
docker-compose -f docker-compose.api.yml down
```

### Manual Docker Build

```bash
# Build development stage
docker build -f Dockerfile.api --target development -t rag-api:dev .

# Run
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name rag-api \
  -v $(pwd)/src:/app/src:ro \
  rag-api:dev
```

**Note**: Changes in `src/` will be reflected automatically when using volume mounts.

---

## 📖 More Resources

- **Full documentation**: [src/api/README.md](src/api/README.md)
- **Tests**: `python tests/test_api.py`
- **Test OpenAI SDK**: `python tests/test_openai_sdk.py`

---

## 🎉 Next steps

1. **Ingest documents**: Before querying, ingest your documents
   ```bash
   python -m src.ingestion.cli /path/to/docs
   ```

2. **Explore the interactive docs**: http://localhost:8000/docs

3. **Integrate into your app**: Use the OpenAI SDK pointing to `http://localhost:8000/v1`

4. **Configure authentication**: Add API keys if you need them (see README)

---

## 💡 Tips

- **Port in use**: Change the port: `uvicorn src.api.app:app --port 8001`
- **Auto-reload**: Already included with `--reload` for local development
- **CORS**: Already configured to allow all origins
- **Logs**: Use `--log-level debug` for more detail

---

Done! Your RAG is now exposed as an OpenAI-compatible API 🎉
