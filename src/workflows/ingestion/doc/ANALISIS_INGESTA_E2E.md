# End-to-End Ingestion Analysis (RAG-Agentic)

This document summarizes an end-to-end analysis of the ingestion flow, highlights resource hot spots, and calls out potential bottlenecks that can cause the system to stall.

## 1. High-Level Flow

1. Ingestion command starts.
2. Discovery scans paths and filters candidates.
3. File loaders parse content (text/PDF/code/etc.).
4. Splitters chunk content.
5. Embeddings are generated.
6. Data is upserted to vector store.
7. Cache metadata is updated.

## 2. Resource Distribution

Key resource consumers:
- CPU: parallel processing (file parsing, chunking, embeddings)
- Memory: large files, large batch sizes, and unbounded concurrency
- I/O: directory traversal and file parsing

## 3. Concurrency Analysis

Observed risks:
- Thread pools dispatch work without backpressure.
- Embedding calls can run concurrently without limits.
- Deep directory structures can cause unbounded stacks in traversal.

## 4. Critical Points Identified

- Unbounded file submission to the executor can overload CPU and memory.
- CSV loaders can create massive numbers of documents when large files are present.
- Scanned PDFs without text can waste time with low value output.
- Duplicate content may be processed multiple times without early de-duplication.

## 5. Environment Variables (Key)

| Variable | Default | Location | Impact |
|---|---|---|---|
| `RAG_PARALLEL_WORKERS` | 4 | pipeline.py | Number of concurrent workers |
| `RAG_EMBED_BATCH_SIZE` | 16 | text_processor.py | Embedding batch size |
| `RAG_SPLIT_BATCH_SIZE` | 128 | text_processor.py | Split batch size |
| `RAG_MAX_DOCS_PER_FILE` | 200000 | text_processor.py | Max documents per file |
| `CONTROL_PLANE_DB_PATH` | ./data/control_plane.db | sqlite manager | SQLite control plane |

## 6. Recommendations

- Add backpressure or a bounded queue before submitting tasks.
- Enforce concurrency limits for embedding calls.
- Add pre-filters for large files (size and type-based).
- Add early duplicate detection before expensive processing.
- Improve PDF quality detection to skip low-value scans.

## 7. Next Steps

- Review `pipeline.py` and `text_processor.py` for concurrency controls.
- Add optional guardrails for CSV/large files.
- Evaluate backpressure integration in the orchestrator.
