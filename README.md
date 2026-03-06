# RAG Agentic Graphiti

**RAG Agentic Graphiti** is a hybrid Retrieval-Augmented Generation (RAG) engine combining **vector search** (Weaviate) and **graph search** (Neo4j), with a **SQLite control plane** for operational metadata. It is designed to integrate seamlessly with local Large Language Models (LLMs) via **LM Studio** using an OpenAI-compatible API.

This system is built for scenarios that require **document ingestion**, **code indexing**, and **semantic relationship mapping** between entities — enabling detailed, context-rich answers.

## 📚 Documentation

- **[Start Here](docs/START_HERE.md)** - Project overview and setup
- **[Documentation Index](docs/DOCS_INDEX.md)** - Complete documentation navigation
- **[Quick Start Guide](docs/QUICK_START_GUIDE.md)** - Getting started
- **[Configuration](docs/CONFIGURATION.md)** - Configuration reference

---

## Overview

- **Hybrid retrieval:** Combines semantic similarity search with graph-based relationship queries.
- **LM Studio integration:** Uses local embedding and language models via API endpoints.
- **Control plane:** Persists operational metadata for resumable scans and runtime state.
- **Document & code ingestion:** Processes 15+ file formats (PDF, DOCX, XLSX, PPTX, ODF, CSV, email, Markdown, plain text, and source code in Python, JS/TS, Java, Go, C#, C/C++, Ruby, PHP).
- **Resumable ingestion queue:** SQLite-backed persistent queue with retry, crash recovery, and priority support.
- **Adaptive worker pool:** Automatically adjusts thread count based on real-time RAM and CPU load.
- **Auto-scan:** Background scheduler re-scans configured paths periodically without manual intervention.
- **Answer modes:** Runtime-configurable response styles (detailed, concise, technical, ELI5) with keyword triggers and per-language instructions.
- **Multi-tenant memory:** Per-session Weaviate tenants for conversation isolation; TTL-based cleanup.
- **Modular architecture:** Each service (vector store, graph store, cache, LLM) can be replaced or extended without affecting the rest of the pipeline.
- **Multiple LLM providers:** LM Studio (default), OpenAI, Ollama, HuggingFace, AnythingLLM, LiteLLM — swappable via `INSTALLED_APPS`.

---

## Requirements

- **Python** 3.12
- **LM Studio** running locally with:
	- At least one **embedding model** loaded
	- At least one **language model** loaded
- **Docker** or **Podman** (for Weaviate, Neo4j)
- Dependencies listed in `requirements.txt`

---

## Installation

1. **Clone the repository**
2. **Create and activate a virtual environment**
3. **Install dependencies**
4. **Configure environment variables**  
	Copy the example `.env` file and adjust values:

---

## Environment Variables

Key `.env` entries you may need to adjust:

- `WEAVIATE_URL` / `WEAVIATE_GRPC_PORT` – REST and gRPC endpoints for your Weaviate deployment.
- `WEAVIATE_CLASS` – Target collection name (defaults to `RAGDocument`).
- `WEAVIATE_CONNECT_RETRIES` / `WEAVIATE_CONNECT_BACKOFF` – How long the app should keep trying while Weaviate boots.
- `LMSTUDIO_HOST` / `LMSTUDIO_PORT` – LM Studio HTTP server host/port.
- `NEO4J_URI`, etc. – Service endpoints when running remotely.

---

## Starting Required Services

### First-time setup

Run the full setup script once to build tool images, install systemd units, permanently enable the tool sockets, and start all services:

```bash
./start-everything.sh
```

### Subsequent starts

Once the sockets are enabled (after first-time setup) you can use `podman-compose` directly — no extra steps:

```bash
COMPOSE_BAKE=false podman-compose up --build -d
```

The preprocessing tool sockets (`tool-document-processor` on port 9106, `tool-extractor` on 9101, `tool-websearch` on 9105) are **permanently enabled** at the user systemd level. They survive reboots and start on-demand when needed — they require no manual intervention when using `podman-compose up`.

This starts:
- **Weaviate** (vector store) on port 8080
- **Neo4j** (graph store) on port 7687
- **RAG API** (OpenAI-compatible REST API) on port 8000

**Note:** Make sure LM Studio is running on your host machine (port 1234) with both an embedding model and a chat model loaded.

### Silencing Podman Compose warnings

Podman prints a warning when it detects the Compose CLI wrapper. Update your Podman config (user-level `~/.config/containers/containers.conf`
or system `/etc/containers/containers.conf`, inside the `[engine]` section) with:

```ini
[engine]
compose_providers = ["/usr/bin/podman-compose"]
compose_warning_logs = false
```

This forces the `podman-compose` provider and stops logging the wrapper notice. When you run the stack manually, also disable Bake:

```bash
COMPOSE_BAKE=false podman-compose up --build -d
```

The `start-everything.sh` script already exports `COMPOSE_BAKE=false`, so it runs without the Bake warning.

Or with Docker Compose:
```bash
docker-compose up --build -d
```

## Logs (Podman / journald)

This stack configures `journald` as the `log driver` (see `podman-compose.yml`), so you can query complete logs with `journalctl`.

- Follow a container log: `journalctl CONTAINER_NAME=rag-graphiti-agentic_weaviate_1 -f`
- In rootless setups it may be in the user journal: `journalctl --user CONTAINER_NAME=rag-graphiti-agentic_weaviate_1 -f`
- Export to a file (example): `journalctl CONTAINER_NAME=rag-graphiti-agentic_weaviate_1 --since today > weaviate.log`
- Export all stack logs to a git-ignored folder: `./scripts/journal_dump.sh`
  - Output: `logs/<YYYY-MM-DD>/<YYYYMMDD-HHMMSS>/`
  - Configurable time window: `SINCE=\"2 hours ago\" UNTIL=\"now\" ./scripts/journal_dump.sh`

Note: the `log driver` is fixed when the container is created; if containers already exist, recreate them: `podman-compose down` then `podman-compose up -d`.

### Auto-export on container stop (systemd)

To automatically export to `logs/` when a project container stops (error or manual), install the systemd watcher (user):

- `cp systemd/rag-graphiti-logwatcher.service ~/.config/systemd/user/`
- Edit `~/.config/systemd/user/rag-graphiti-logwatcher.service` and set `REPO_DIR=/absolute/path/to/repo`
- `systemctl --user daemon-reload`
- `systemctl --user enable --now rag-graphiti-logwatcher.service`

To disable:

- `systemctl --user disable --now rag-graphiti-logwatcher.service`

Or, if you prefer to keep it installed but not exporting, toggle `ENABLE_LOG_EXPORT=1` / `#Environment=ENABLE_LOG_EXPORT=0` in the unit file.

## Ingestion: preserving duplicates by path

If you want certain files to be ingested even when their content is identical (because the path/package tree matters), configure `DUPLICATES_DOC_EXCEPTIONS` in `src/settings.py` or `data/settings.json`.

- Default includes: `__init__.py`
- Supported entries: basename, glob patterns, directory prefixes (ending with `/`), or regex (`re:` prefix)
- Example: `DUPLICATES_DOC_EXCEPTIONS = ("__init__.py", "setup.py", "**/*.config")`

---

## Usage

### OpenAI-Compatible REST API ✨

The RAG API is **automatically started** when you run `podman-compose up --build -d`. It's accessible at `http://localhost:8000` (default).

This API can run in **OpenAI** or **Ollama** compatibility mode (controlled by `API_MODE`). To see what your instance is currently exposing, call `GET /` and inspect `api_mode` + `endpoints`.

**Alternative: Run API locally (without containers):**

```bash
# Local with auto-reload (services must be running)
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

**Available endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/models` | List available models |
| `POST` | `/v1/chat/completions` | Chat completion (OpenAI-compatible) |
| `POST` | `/v1/responses` | Modern endpoint with structured metadata |
| `POST` | `/v1/embeddings` | Generate embeddings/vectors |
| `POST` | `/rag/query` | Direct RAG query with metadata |
| `POST` | `/rag/ingest` | Trigger ingestion via API |
| `GET` | `/rag/answer-modes` | List answer modes |
| `PUT` | `/rag/answer-modes/{name}` | Create/update an answer mode |
| `DELETE` | `/rag/answer-modes/{name}` | Delete an answer mode |
| `GET` | `/api/stats/rag` | Overall stats: objects, tenants, graph counts |
| `GET` | `/api/stats/graph` | Neo4j node/relation breakdown by type |
| `GET` | `/api/stats/vector` | Weaviate collection stats per tenant |
| `GET` | `/exclusions/` | Read `.ingestignore` entries |
| `POST` | `/exclusions/` | Update `.ingestignore` entries at runtime |
| `GET` | `/volumes/` | List configured external volumes |
| `GET` | `/volumes/status` | Check mount availability of each volume |
| `POST` | `/volumes/{name}/mark-available` | Mark a volume as available |
| `GET` | `/api/system/autostart` | Get systemd autostart status |
| `POST` | `/api/system/autostart` | Enable/disable systemd autostart |
| `GET` | `/api/files/` | List tracked ingested files |
| `GET` | `/health` | Health check |

**Interactive docs:**

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**Example usage with the OpenAI SDK:**

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

**More information:**

- Full documentation: [src/api/README.md](src/api/README.md)
- Tests: `python tests/test_api.py`

---

### Ingest Documents and Code

Supported formats:

| Category | Extensions |
|---|---|
| Documents | `.pdf`, `.docx`, `.doc`, `.txt`, `.md`, `.rst`, `.log` |
| Spreadsheets | `.xlsx`, `.ods`, `.csv` |
| Presentations | `.pptx`, `.ppt` |
| Email | `.eml`, `.msg` |
| Source code | `.py`, `.js`, `.ts`, `.java`, `.go`, `.cs`, `.c`, `.cpp`, `.h`, `.rb`, `.php` |

During ingestion:

- Text is split into chunks (with Markdown-aware and semantic splitting options)
- Embeddings are generated via LM Studio
- Data is inserted into Weaviate
- Entities and relationships are extracted and inserted into Neo4j (when `NEO4J_ENABLED=true`)
- Each file is tracked in the ledger for content-level deduplication (SHA-256) and mtime-based skip logic

To ignore files/directories from ingestion, add patterns and paths to `.ingestignore`
(supports relative or absolute entries). You can also manage exclusions at runtime via the REST API:

```bash
# Read current exclusions
curl http://localhost:8000/exclusions/

# Update exclusions (replaces entire list)
curl -X POST http://localhost:8000/exclusions/ \
  -H "Content-Type: application/json" \
  -d '{"excludes": ["node_modules/", "**/__pycache__/**", "data/private/**"]}'
```

#### Resumable ingestion

Enable with `INGESTION_RESUMABLE_ENABLED=true`. Files are queued persistently in SQLite and retried with exponential backoff on failure. Crashes mid-run are recovered automatically on next start.

```bash
# Inspect queue state
python -m src.workflows.ingestion.checkpoint.checkpoint_cli status

# Re-run with reclassification (ignores all cached scores)
python -m src.main --ingest /path --reclassify
```

---

### Query the RAG

**Interactive CLI mode**

```bash
python -m src.query.cli
```

**Single query**

```bash
python -m src.query.cli "Explain the architecture"
python -m src.query.cli "Explain the architecture" --top-k 10
```

**HTTP (recommended for integrations)**

```bash
# Direct RAG endpoint
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What are the main topics?","top_k":5}' | jq

# OpenAI-compatible
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-local","messages":[{"role":"user","content":"hello"}],"top_k":5}' | jq
```

**Answer Modes (runtime, configurable)**

Answer modes let you control the response style without restarting the API. Built-in modes: `detailed` (default), `concise`, `technical`, `eli5`. Modes activate automatically when the query contains a trigger keyword (e.g. "explain briefly" → concise mode), or you can specify one explicitly.

```bash
# List modes
curl -sS http://localhost:8000/rag/answer-modes | jq

# Create/update a mode
curl -sS -X PUT "http://localhost:8000/rag/answer-modes/conciso?merge=true" \
  -H "Content-Type: application/json" \
  -d '{"description":"Respuesta corta","triggers":["conciso","breve"]}' | jq

# Delete a mode
curl -sS -X DELETE http://localhost:8000/rag/answer-modes/conciso | jq
```

More detailed guide: `docs/QUERYING_GUIDE.md`

---

### Socket Server Mode (Remote Access)

Start the server:

Connect from another machine:

---

## Neo4j Graph Store

Neo4j is **optional and off by default**. Enable it by setting `NEO4J_ENABLED=true` in your `.env` or `data/settings.json`. When enabled:

- `RuntimeFactory` initializes `Neo4jRepository` on startup and closes it on shutdown.
- The `/api/stats/graph` endpoint returns real node/relation counts grouped by type.
- The `/api/stats/rag` endpoint includes live `graph_nodes` and `graph_relations` counts.
- Ingestion extracts entities and relationships from documents and writes them to Neo4j.

When `NEO4J_ENABLED=false` (default), all graph endpoints return empty stats — no errors.

## External Volumes

The API can manage external mount points (USB drives, NFS shares) via `data/settings.json`:

```bash
# Add a volume
curl -X POST http://localhost:8000/volumes/add \
  -H "Content-Type: application/json" \
  -d '{"name":"usb","primary":"/mnt/usb","fallback":"/data/fallback","mount":"/mnt/usb"}'

# Check mount status
curl http://localhost:8000/volumes/status
```

Volumes with a `.volume-available` marker file in their `primary` path are considered mounted.

## Integrating on Another Machine

If another machine has **LM Studio** and similar specs:

1. Clone this repository.
2. Configure `.env` with the **remote** Weaviate and Neo4j URLs (the cache/checkpointing layer now relies on the local SQLite control plane).
3. Run:
	or connect via the socket server.

> The provided `podman-compose.yml` uses `network_mode: host`, which simplifies external connections within the same network.

---

## External Apps (Plugins)

This project supports Django-like app registration:

- Enable apps via `Config.INSTALLED_APPS` (stored in `data/settings.json`).
- Apps run a `ready()` hook to register components (e.g. providers).
- Optional Python entry-point discovery can be enabled with:
  - `AUTOLOAD_APP_ENTRYPOINTS=true`
  - `APP_ENTRYPOINT_GROUP=rag_agentic_graphiti.apps`

### Provider Gateway Example (LiteLLM-like)

Set:

- `PROVIDER=litellm`
- `LITELLM_TARGET_PROVIDER=lmstudio` (or `openai`)

This uses a gateway adapter that delegates to another provider, to simulate how
an external gateway/provider would integrate.

### Provider Apps

- Only `ollama` is treated as a built-in provider (core `rag`).
- Providers like `lmstudio`, `anythingllm`, and `huggingface` are enabled via `INSTALLED_APPS`.

### Weaviate embedding dimension changes

Weaviate collections require a consistent vector length. If you change embedding models (e.g., 384 → 768 dimensions), you must either:
- Keep using the original dimension/model, or
- Recreate the Weaviate collection/volume, or
- Use a new `WEAVIATE_CLASS` for the new dimension.

---

## Code Quality and Monitoring

The system includes comprehensive code quality monitoring tools to detect legacy code, bloat, and unused code.

### Monitoring Features

The monitoring system provides:

1. **Static Analysis with Vulture**: Detects dead/unused code across the entire codebase
2. **Dynamic Analysis with Coverage**: Tracks code execution during development to identify unused code paths
3. **Real-time Monitoring**: Optional background monitoring that aggregates coverage data across all pipelines
4. **Pipeline Classification**: Identifies which code belongs to specific pipelines (ingestion, web queries, RAG queries, file processing, etc.)
5. **Detailed Reports**: Generates reports in CSV, TXT, and Markdown formats showing:
   - Code snippets with context
   - File locations and line numbers
   - Status (unused, rarely used, legacy)
   - Object type (function, class, variable)
   - Pipeline classification

### Usage

#### Development Mode
When running in development mode, the system automatically enables coverage monitoring:

```bash
./start-everything.sh
```

The script will prompt you:
- "Are you running in development mode? (y/N):" - Answer 'y' to enable coverage
- "Enable monitoring features? (y/N):" - Answer 'y' to enable optional monitoring features

#### Environment Variables
Control monitoring behavior with these environment variables in `.env`:

```bash
# Monitoring Configuration
ENABLE_COVERAGE_MONITORING=true          # Enable coverage.py dynamic analysis
ENABLE_VULTURE_MONITORING=true           # Enable vulture static analysis
ENABLE_REALTIME_MONITORING=false         # Enable real-time background monitoring
MONITORING_MODE=development              # development or production
```

#### Manual Monitoring
Run the monitoring tools manually:

```bash
# Run bloat analyzer
python -m tools.monitoring.src.bloat_analyzer

# Run real-time monitor
python -m tools.monitoring.src.realtime_monitor

# Run monitoring daemon (full analysis)
python -m tools.monitoring.src.monitor_daemon
```

### Legacy Code Cleanup

A dedicated script is available to remove legacy integration artifacts:

```bash
./legacy-cleanup.sh
```

This interactive script will:
1. Find and remove qdrant integration artifacts
2. Find and remove redis integration artifacts
3. Clean up requirements.txt, Dockerfile, and configuration files
4. Remove Python imports related to removed integrations
5. Run bloat analyzer for further detection

**Important**: The script creates backup files with `.backup` extension before making changes.

### Reports
Monitoring reports are saved to `/app/reports/` in the monitoring container:
- `bloat/` - Bloat analysis reports
- `coverage/` - Coverage reports
- `vulture/` - Vulture static analysis reports

## Environment Variables Reference

Key variables beyond the basics:

| Variable | Default | Description |
|---|---|---|
| `NEO4J_ENABLED` | `false` | Enable Neo4j graph store |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection URI |
| `INGESTION_RESUMABLE_ENABLED` | `true` | Enable SQLite-backed resumable queue |
| `RAG_ADAPTIVE_WORKERS` | `true` | Enable adaptive thread pool sizing |
| `RAG_ADAPTIVE_RAM_HIGH` | `75` | RAM% threshold to reduce workers |
| `RAG_ADAPTIVE_RAM_LOW` | `60` | RAM% threshold to increase workers |
| `RAG_ADAPTIVE_CPU_HIGH` | `2.5` | CPU load avg threshold to reduce workers |
| `RAG_ADAPTIVE_BATCH_SIZE` | `10` | Files per ingestion sub-batch |
| `AUTO_SCAN_ENABLED` | `false` | Enable background auto-scan |
| `AUTO_SCAN_INTERVAL` | `300` | Seconds between auto-scans |
| `RESOURCE_MODE` | `SAVER` | `SAVER` / `BALANCED` / `PERFORMANCE` |
| `API_MODE` | `openai` | `openai` or `ollama` compatibility mode |
| `WEB_SEARCH_ENABLED` | `false` | Enable SearXNG web fallback |
| `DUPLICATES_DOC_EXCEPTIONS` | `("__init__.py",)` | Paths ingested even when duplicate |

## Roadmap

- Improved relation extraction with prompt templates
- Lightweight web-based query interface
- Enhanced monitoring with AI-powered code suggestions

---

## License

This project is **proprietary**.  
Use, copying, distribution, or modification is prohibited without explicit written permission from the author.

---

**Author:**  
José Luis López López Prieto
