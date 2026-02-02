# RAG API - Ollama-like

An Ollama-like API to expose the RAG system as a REST service. This API prioritizes simple `/api/*` endpoints and RAG-specific `/rag/*` endpoints.

## Requirements

- **Python 3.12** (to stay consistent with the rest of the project)
- Backend services running (Weaviate, Neo4j, LM Studio) plus the SQLite control plane (`data/control_plane.db`) that now owns cache/checkpoint tasks (context checkpoint compaction, metadata, resumability).

## Features

- **Ollama-like core**: `/api/generate`, `/api/chat`, `/api/embeddings`, `/api/tags`
- **RAG endpoints**: `/rag/ingest`, `/rag/query`, `/rag/tools/*`
- **FastAPI**: Modern, fast framework
- **Automatic docs**: Swagger UI and ReDoc included
- **Type-safe**: Automatic validation with Pydantic
- **Async/Await**: Efficient handling of concurrent requests

## Implemented Endpoints

### Core (Ollama-like)

- POST `/api/generate`
- POST `/api/chat`
- POST `/api/embeddings`
- POST `/api/pull` (returns 501)
- GET `/api/tags`

### RAG-Specific

- POST `/rag/ingest`
- POST `/rag/query`
- GET `/rag/answer-modes`
- PUT `/rag/answer-modes`
- GET `/rag/answer-modes/{mode}`
- PUT `/rag/answer-modes/{mode}`
- DELETE `/rag/answer-modes/{mode}`
- POST `/rag/tools/zip`
- POST `/rag/tools/office`
- POST `/rag/tools/ocr`
- GET `/rag/files/{id}/location`
- GET `/rag/files/{id}/metadata`
- GET `/health`

### Example: `/api/chat`

**Request:**
```json
{
  "model": "rag-default",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is machine learning?"}
  ],
  "options": {"temperature": 0.7, "max_tokens": 512, "top_k": 5}
}
```

**Response:**
```json
{
  "model": "rag-default",
  "created_at": "2024-01-01T00:00:00Z",
  "message": {"role": "assistant", "content": "Machine learning is..."},
  "done": true,
  "sources": [
    {"path": "/path/to/doc.pdf", "relevance_score": 0.892}
  ]
}
```

### Example: `/api/generate`

**Request:**
```json
{
  "model": "rag-default",
  "prompt": "Explain neural networks in simple terms",
  "system": "Be concise.",
  "options": {"temperature": 0.7, "max_tokens": 256}
}
```

### Example: `/api/embeddings`

**Request:**
```json
{
  "model": "text-embedding-ada-002",
  "input": ["Hello world", "Machine learning is great"]
}
```

**Response:**
```json
{
  "model": "text-embedding-ada-002",
  "embeddings": [
    [0.123, -0.456, 0.789],
    [0.111, -0.222, 0.333]
  ]
}
```

### Example: `/rag/query`

**Request:**
```json
{
  "query": "What is machine learning?",
  "top_k": 5,
  "filters": {"source": "notes.pdf"}
}
```

### Example: Answer modes (runtime)

**List modes**
```bash
curl -sS http://localhost:8000/rag/answer-modes | jq
```

**Create/Update one mode**
```bash
curl -sS -X PUT "http://localhost:8000/rag/answer-modes/analitico?merge=true" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Respuesta con análisis previo",
    "triggers": ["modo analitico"],
    "pipeline": [
      {"type": "preanalysis", "config": {"enabled": true, "max_tokens": 256}},
      {"type": "answer"}
    ]
  }' | jq
```

### Example: `/rag/ingest`

**Request:**
```json
{
  "paths": ["/path/to/docs"],
  "dry_run": false,
  "max_files": 100
}
```

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure services are running:
   - Weaviate (vector store)
   - Neo4j (graph store)
   - LM Studio (LLM)
   - SQLite control plane (data/control_plane.db) for cache/checkpoint metadata

3. Configure environment variables in `.env` (see `src/settings.py`)

## Run the API

```bash
# Local with auto-reload
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# Or with Docker/Podman (includes all services, mounts src/ for hot-reload)
docker-compose -f docker-compose.api.yml up
```

## Interactive Documentation

Once the API is running, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Example Requests

```bash
# Chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-default",
    "messages": [
      {"role": "user", "content": "What is machine learning?"}
    ],
    "options": {"temperature": 0.7}
  }'

# Generate
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-default",
    "prompt": "Explain neural networks"
  }'

# Embeddings
curl -X POST http://localhost:8000/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "text-embedding-ada-002",
    "input": "Hello world"
  }'
```

## Custom Parameters

The API includes RAG-specific additional parameters:

- **`top_k`**: Number of documents to retrieve from the vector store (default: 5)

Example:
```json
{
  "model": "rag-default",
  "messages": [...],
  "options": {"top_k": 10}
}
```

## Architecture

```
┌─────────────────┐
│   Client        │
│ (Ollama-like)   │
└────────┬────────┘
         │ HTTP/REST
         ▼
┌─────────────────┐
│   FastAPI       │
│   API Layer     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ RAGOrchestrator │─────►│  Weaviate    │ (Vector Search)
│                 │      └──────────────┘
│                 │      ┌──────────────┐
│                 │─────►│  Neo4j       │ (Graph Search)
│                 │      └──────────────┘
│                 │      ┌──────────────┐
│                 │─────►│  LM Studio   │ (LLM Generation)
└─────────────────┘      └──────────────┘
```

## Logging

The API uses Python's `logging` module. To adjust the log level:

```python
# In src/api/app.py
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG for more details
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
```

## CORS

By default, CORS is enabled for all origins (`allow_origins=["*"]`). If needed, you can set specific origins in `src/api/app.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Docker Setup

`Dockerfile` uses a multi-stage build for local development:

- **Stage `base`**: Core dependencies (Python 3.12, system packages, requirements.txt)
- **Stage `development`**: Auto-reload, pytest, code mounted as a volume, healthcheck

See [docker-compose.api.yml](../../docker-compose.api.yml) for usage examples.

## Current Limitations

1. **No authentication**: You can add JWT/API keys if needed
2. **No rate limiting**: Consider adding `slowapi` if needed
3. **Streaming not implemented**: Endpoints do not support `stream=true` yet
4. **/api/pull**: Not supported (returns 501)

## Potential Improvements

- [ ] Add authentication (API keys or JWT)
- [ ] Implement rate limiting if needed
- [ ] Add streaming support (SSE)
- [ ] Metrics and observability (Prometheus/OpenTelemetry)
- [ ] Integration tests for `/rag/*` tools

## Usage Examples

### cURL

```bash
# Chat
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-default",
    "messages": [{"role": "user", "content": "What is ML?"}]
  }'

# Generate
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-default", "prompt": "Explain ML"}'

# Embeddings
curl -X POST http://localhost:8000/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-ada-002", "input": "Hello world"}'
```

## Tests

API tests are in [`tests/integration/test_api.py`](../../tests/integration/test_api.py):

```bash
# Run tests
python tests/integration/test_api.py
```

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

## License

Same as the main project.
