# API Quick Start

## Prerequisites

- Weaviate reachable on `localhost:8080`
- LM Studio reachable on `localhost:1234`
- Neo4j optional unless you enable `NEO4J_ENABLED=true`
- SQLite control plane available at `data/control_plane.db`

## Start the stack

### Full stack

```bash
./start-everything.sh
```

### Manual daily startup

```bash
COMPOSE_BAKE=false podman-compose up --build -d
```

### Local API only

```bash
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

## Smoke checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/
curl http://localhost:1234/v1/models
curl http://localhost:8080/v1/.well-known/ready
```

## OpenAI-compatible examples

```bash
curl http://localhost:8000/v1/models | jq

curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"rag-local",
    "messages":[{"role":"user","content":"What does this project do?"}],
    "top_k": 5
  }' | jq

curl -X POST http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model":"rag-local",
    "input":"Summarize the system architecture"
  }' | jq
```

## RAG-native examples

```bash
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What are the main topics?","top_k":3}' | jq

curl -sS http://localhost:8000/rag/answer-modes | jq
```

## Ollama-compatible mode

If you set `API_MODE=ollama`, the API exposes routes such as:

```bash
curl http://localhost:8000/api/tags | jq

curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model":"rag-local",
    "messages":[{"role":"user","content":"Hello"}],
    "options":{"top_k":5}
  }' | jq
```

## Useful operational routes

```bash
curl http://localhost:8000/api/stats/rag | jq
curl http://localhost:8000/volumes/status | jq
curl http://localhost:8000/exclusions/ | jq
```

## Test

```bash
pytest tests/integration/rag/test_api.py
```

## Related docs

- `src/api/README.md`
- `docs/QUERYING_GUIDE.md`
- `docs/CONFIGURATION.md`
