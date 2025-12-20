# RAG API - OpenAI Compatible

An OpenAI-compatible API to expose the RAG system as a REST service. This API lets any application that uses the OpenAI format connect to your RAG without changes.

## Requirements

- **Python 3.12** (to stay consistent with the rest of the project)
- Backend services running (Weaviate, Neo4j, Redis, LM Studio)

## Features

- **100% OpenAI compatible**: Same request/response structure
- **FastAPI**: Modern, fast framework
- **Automatic docs**: Swagger UI and ReDoc included
- **Type-safe**: Automatic validation with Pydantic
- **Async/Await**: Efficient handling of concurrent requests

## Implemented Endpoints

### 1. GET `/v1/models`

Lists the available models in the system.

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "rag-local",
      "object": "model",
      "created": 1234567890,
      "owned_by": "rag-local"
    },
    {
      "id": "lmstudio-liquidai",
      "object": "model",
      "created": 1234567890,
      "owned_by": "lmstudio"
    }
  ]
}
```

### 2. POST `/v1/chat/completions` (Legacy - Most Used)

Classic OpenAI-compatible chat endpoint. Ideal for existing UIs.

**Request:**
```json
{
  "model": "rag-local",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "What is machine learning?"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "top_k": 5
}
```

**Response:**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "rag-local",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Machine learning is...\n\nSources:\n- /path/to/doc.pdf (score: 0.892)"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 100,
    "total_tokens": 150
  }
}
```

### 3. POST `/v1/responses` (Modern)

Modern endpoint with advanced metadata support and structured sources.

**Request:**
```json
{
  "model": "rag-local",
  "input": "What is machine learning?",
  "temperature": 0.7,
  "max_tokens": 1024,
  "top_k": 5
}
```

**Response:**
```json
{
  "id": "resp-abc123",
  "object": "response",
  "created": 1234567890,
  "model": "rag-local",
  "output": [
    {
      "type": "text",
      "text": "Machine learning is a subset of artificial intelligence..."
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 100,
    "total_tokens": 120
  },
  "metadata": {
    "retrieved_count": 5,
    "sources": [
      {
        "path": "/path/to/document.pdf",
        "relevance_score": 0.892
      },
      {
        "path": "/path/to/another.docx",
        "relevance_score": 0.765
      }
    ],
    "query": "What is machine learning?",
    "temperature": 0.7,
    "max_tokens": 1024
  }
}
```

### 4. POST `/v1/embeddings`

Generates embeddings (vectors) for text.

**Request:**
```json
{
  "model": "text-embedding-ada-002",
  "input": "Hello world"
}
```

Or multiple texts:
```json
{
  "model": "text-embedding-ada-002",
  "input": ["Hello world", "Machine learning is great"]
}
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [0.123, -0.456, 0.789, ...],
      "index": 0
    }
  ],
  "model": "text-embedding-ada-002",
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 0,
    "total_tokens": 10
  }
}
```

### 5. GET `/health`

Service health check.

**Response:**
```json
{
  "status": "healthy",
  "rag_initialized": true,
  "embedding_initialized": true
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
   - Redis (cache)
   - LM Studio (LLM)

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

## Use with Existing Clients

### Python (OpenAI SDK)

```python
from openai import OpenAI

# Configure the client to point to your local API
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # The API does not require authentication (you can add it)
)

# Use it as if it were OpenAI
response = client.chat.completions.create(
    model="rag-local",
    messages=[
        {"role": "user", "content": "What is machine learning?"}
    ],
    temperature=0.7,
    max_tokens=1024
)

print(response.choices[0].message.content)
```

### cURL

```bash
# Chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-local",
    "messages": [
      {"role": "user", "content": "What is machine learning?"}
    ],
    "temperature": 0.7
  }'

# Embeddings
curl -X POST http://localhost:8000/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "text-embedding-ada-002",
    "input": "Hello world"
  }'
```

### JavaScript/TypeScript

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
  temperature: 0.7,
});

console.log(response.choices[0].message.content);
```

## Custom Parameters

The API includes RAG-specific additional parameters:

- **`top_k`**: Number of documents to retrieve from the vector store (default: 5)

Example:
```json
{
  "model": "rag-local",
  "messages": [...],
  "top_k": 10
}
```

## Architecture

```
┌─────────────────┐
│   Client        │
│ (OpenAI SDK)    │
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

`Dockerfile.api` uses a multi-stage build for local development:

- **Stage `base`**: Core dependencies (Python 3.12, system packages, requirements.txt)
- **Stage `development`**: Auto-reload, pytest, code mounted as a volume, healthcheck

See [docker-compose.api.yml](../../docker-compose.api.yml) for usage examples.

## Current Limitations

1. **No authentication**: You can add JWT/API keys if needed
2. **No rate limiting**: Consider adding `slowapi` if needed
3. **Streaming not implemented**: Endpoints do not support `stream=true` yet
4. **GET/DELETE /v1/responses/{id}**: Not implemented (returns 501)

## Potential Improvements

- [ ] Add authentication (API keys or JWT)
- [ ] Implement rate limiting if needed
- [ ] Add streaming support (SSE)
- [ ] Persist responses for GET/DELETE `/v1/responses/{id}`
- [ ] Metrics and observability (Prometheus/OpenTelemetry)
- [ ] Integration tests

## Usage Examples in Different Languages

### Python with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

# Chat completion
response = client.chat.completions.create(
    model="rag-local",
    messages=[{"role": "user", "content": "What is machine learning?"}],
    temperature=0.7
)
print(response.choices[0].message.content)

# Embeddings
embedding = client.embeddings.create(
    model="text-embedding-ada-002",
    input="Text to vectorize"
)
print(f"Vector dimension: {len(embedding.data[0].embedding)}")
```

### JavaScript/TypeScript

```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'not-needed',
});

const response = await client.chat.completions.create({
  model: 'rag-local',
  messages: [{ role: 'user', content: 'What is machine learning?' }],
});

console.log(response.choices[0].message.content);
```

### cURL

```bash
# Chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-local",
    "messages": [{"role": "user", "content": "What is ML?"}]
  }'

# Embeddings
curl -X POST http://localhost:8000/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-ada-002", "input": "Hello world"}'
```

### Langchain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    openai_api_base="http://localhost:8000/v1",
    openai_api_key="not-needed",
    model_name="rag-local",
)

response = llm.invoke("What is machine learning?")
print(response.content)
```

### LlamaIndex

```python
from llama_index.llms.openai import OpenAI
from llama_index.core import Settings

llm = OpenAI(
    api_base="http://localhost:8000/v1",
    api_key="not-needed",
    model="rag-local",
)

Settings.llm = llm
# Now all components will use your RAG
```

## Tests

API tests are in [`tests/test_api.py`](../../tests/test_api.py):

```bash
# Run tests
python tests/test_api.py

# Test with OpenAI SDK
python tests/test_openai_sdk.py
```

## Resources

- [OpenAI API documentation](https://platform.openai.com/docs/api-reference)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

## License

Same as the main project.
