# RAG API

The API supports two HTTP compatibility families selected by `API_MODE`:

- `openai` (default): `/v1/models`, `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, `/v1/files`
- `ollama`: `/api/chat`, `/api/generate`, `/api/embeddings`, `/api/tags`, `/api/chat/memory`

RAG-specific routes such as `/rag/query`, `/rag/ingest`, `/rag/answer-modes`, `/volumes/*`, `/exclusions/*`, and `/api/stats/*` are always mounted.

## Run locally

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

## Main route groups

### OpenAI mode

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/responses/{response_id}`
- `DELETE /v1/responses/{response_id}`
- `POST /v1/embeddings`
- `POST /v1/files`
- `GET /v1/files`
- `DELETE /v1/files/{file_id}`
- `POST /v1/files/{file_id}/promote`

### Ollama mode

- `POST /api/generate`
- `POST /api/chat`
- `POST /api/chat/memory`
- `POST /api/embeddings`
- `POST /api/pull` (`501`)
- `GET /api/tags`
- `GET /api/version`
- `GET /api/ps`
- `POST /api/show`

### RAG and operations

- `POST /rag/query`
- `POST /rag/ingest`
- `GET|PUT|DELETE /rag/answer-modes/{mode_name}`
- `PUT /rag/answer-modes`
- `POST /rag/tools/zip`
- `POST /rag/tools/office`
- `POST /rag/tools/ocr`
- `GET /rag/files/{file_id}/location`
- `GET /rag/files/{file_id}/metadata`
- `GET /api/stats/rag`
- `GET /api/stats/graph`
- `GET /api/stats/vector`
- `GET /api/stats/metrics`
- `GET|POST /api/system/autostart`
- `GET /api/system/autostart/status`
- `GET|POST /exclusions/`
- `GET|POST /volumes/`
- `POST /volumes/add`
- `PUT|DELETE /volumes/{volume_name}`
- `GET /volumes/status`
- `POST /volumes/{volume_name}/mark-available`
- `GET /health`

## Notes

- The root endpoint `GET /` reports the active `api_mode` and the primary endpoints for that mode.
- `src/api/app.py` always mounts the RAG, files, stats, volumes, exclusions, and system routers regardless of compatibility mode.
- Temporal file upload flows are implemented under `src/api/files/router.py`.
- Runtime resources are created by `src/api/runtime.py`.

## Verify with tests

```bash
pytest tests/integration/rag/test_api.py
```
