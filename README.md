# RAG Agentic Graphiti

**RAG Agentic Graphiti** is a hybrid Retrieval-Augmented Generation (RAG) engine combining **vector search** (Weaviate) and **graph search** (Neo4j), with **Redis caching** for faster responses. It is designed to integrate seamlessly with local Large Language Models (LLMs) via **LM Studio** using an OpenAI-compatible API.

This system is built for scenarios that require **document ingestion**, **code indexing**, and **semantic relationship mapping** between entities — enabling detailed, context-rich answers.

---

## Overview

- **Hybrid retrieval:** Combines semantic similarity search with graph-based relationship queries.
- **LM Studio integration:** Uses local embedding and language models via API endpoints.
- **Caching layer:** Speeds up repeat queries using Redis.
- **Document & code ingestion:** Processes text, markdown, and source code with automatic entity/relation extraction.
- **Socket server option:** Enables network-based queries from external clients.
- **Modular architecture:** Each service (vector store, graph store, cache, LLM) can be replaced or extended without affecting the rest of the pipeline.

---

## Requirements

- **Python** 3.12
- **LM Studio** running locally with:
	- At least one **embedding model** loaded
	- At least one **language model** loaded
- **Docker** or **Podman** (for Weaviate, Redis, Neo4j)
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
- `REDIS_HOST`, `NEO4J_URI`, etc. – Service endpoints when running remotely.

---

## Starting Required Services

You can run Weaviate, Redis, and Neo4j using the provided **Podman Compose** file.
Make sure the Weaviate service:
- exposes both REST (8080) and gRPC (50051) ports so the client can complete its startup checks
- sets a stable `CLUSTER_HOSTNAME` (e.g., `weaviate-node-1`) so restarts reuse the same Raft identity

Or with Docker Compose:

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

### Ingest Documents and Code

Supported formats:

- `.pdf`, `.docx`, `.txt`, `.md` → processed as text
- `.py`, `.js` → structural summaries (functions, classes)

During ingestion:

- Text is split into chunks
- Embeddings are generated via LM Studio
- Data is inserted into Weaviate
- Entities and relationships are extracted and inserted into Neo4j

To ignore files/directories from ingestion, add patterns and paths to `.ingestignore`
(supports relative or absolute entries).

---

### Query the RAG

**Interactive CLI mode**

**Single query**

---

### Socket Server Mode (Remote Access)

Start the server:

Connect from another machine:

---

## Integrating on Another Machine

If another machine has **LM Studio** and similar specs:

1. Clone this repository.
2. Configure `.env` with the **remote** Weaviate, Redis, and Neo4j URLs.
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

### Local GPU Embeddings

Set `EMBEDDING_BACKEND=local_gpu` to run sentence-transformers embeddings locally while LM Studio continues to handle chat completions.
Install deps with `pip install -r requirements.txt`.
If `EMBEDDING_BACKEND=local_gpu` is set but `torch`/`sentence-transformers` are missing, the app falls back to the configured provider embeddings.
Tune `LOCAL_GPU_DEVICE` (`cuda`, `cuda:0`, `auto`, `cpu`), `LOCAL_GPU_EMBED_MODEL` (sentence-transformers model name), and `LOCAL_GPU_BATCH_SIZE` (default 32) via `.env`.
The helper lives in `src/utils/local_gpu`: it wraps the CUDA-aware encoder with an optional Redis cache, so embeddings stay on the GPU while LM Studio is only used for chat. Ensure `torch` and `sentence-transformers` are installed and a CUDA driver is available.

### Weaviate embedding dimension changes

Weaviate collections require a consistent vector length. If you change embedding models (e.g., 384 → 768 dimensions), you must either:
- Keep using the original dimension/model, or
- Recreate the Weaviate collection/volume, or
- Use a new `WEAVIATE_CLASS` for the new dimension.

---

## Roadmap

- Support for additional document formats
- Custom preprocessing plugins
- Improved relation extraction with prompt templates
- Lightweight web-based query interface
- External apps / providers via registry

---

## License

This project is **proprietary**.  
Use, copying, distribution, or modification is prohibited without explicit written permission from the author.

---

**Author:**  
José Luis López López Prieto
