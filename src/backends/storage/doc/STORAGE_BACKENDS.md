# Storage Backends

This document provides an overview of all storage backends used in the RAG project.

## Architecture

The RAG system uses a multi-backend storage architecture to leverage the strengths of different database technologies:

```
┌─────────────────────────────────────────────────┐
│             RAG Application Layer                │
└─────────────────────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          │   Storage Interfaces   │
          └───────────┬───────────┘
                      │
    ┌─────────────────┼─────────────────┬─────────────┐
    │                 │                 │             │
┌───▼────┐     ┌─────▼──────┐    ┌────▼──────────┐
│Weaviate│     │   Neo4j    │    │ SQLite control│
│(Vector)│     │  (Graph)   │    │ plane (cache/ │
└────────┘     └────────────┘    │ checkpoint)   │
                                 └───────────────┘
```

## 1. Vector Store - Weaviate

**Purpose**: Semantic search and vector similarity operations

**Location**: [src/storage/vector/weaviate_repository/](../vector/weaviate_repository/)

### Features
- Stores document embeddings for semantic search
- HNSW (Hierarchical Navigable Small World) index for fast similarity search
- Supports hybrid search (vector + keyword)
- Multi-tenant architecture support

### Configuration
```bash
WEAVIATE_URL=http://localhost:8080
WEAVIATE_API_KEY=optional-api-key
```

### Schema
Defined in [repository.py](../vector/weaviate_repository/repository.py) and [schema.py](../vector/weaviate_repository/schema.py)

### Key Operations
- `upsert_documents()`: Add/update document embeddings
- `search()`: Semantic search
- `hybrid_search()`: Combined vector + keyword search
- `delete_by_id()`: Remove documents

### Related Files
- [src/storage/vector/weaviate_repository/repository.py](../vector/weaviate_repository/repository.py)
- [src/storage/vector/weaviate_repository/schema.py](../vector/weaviate_repository/schema.py)

## 2. Graph Store - Neo4j

**Purpose**: Knowledge graph for entity relationships, provenance tracking, and RAG context enrichment

**Location**: [src/backends/storage/graph/neo4j_repository.py](../graph/neo4j_repository.py)

**Optional** — activate with `NEO4J_ENABLED=true`. When disabled, all graph endpoints return zeros gracefully.

### Graph Model

```
Layer 1 — Filtering:
  (:Installation)-[:HAS_GROUP]->(:Group)-[:HAS_EMBEDDING]->(:Embedding)

Layer 2 — Knowledge graph:
  (:Chunk {chunk_id, source, contribution_type})
  (:Entity {key, name, entity_type})
  (:Topic  {name})
  (:Source {title, type, shareable, author})
  (:User   {user_id})

  (:Chunk)-[:MENTIONS]->(:Entity)
  (:Entity)-[:RELATED_TO]->(:Entity)   # co-occurrence
  (:Entity)-[:PART_OF]->(:Topic)
  (:Chunk)-[:ORIGINATED_FROM]->(:Source)
  (:Chunk)-[:OWNED_BY]->(:User)
```

### Contribution Types & Shareability

`contribution_type` on `Chunk` and `shareable` on `Source` are inferred from `document_type` at ingestion time:

| document_type | contribution_type | shareable |
|---|---|---|
| `conversation`, `note`, `memo` | `original` | `True` |
| `chat` | `ai_assisted` | `True` |
| `pdf`, `epub`, `book`, `docx` | `citation` | `False` |
| unknown | `unknown` | `False` |

### Configuration
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_ENABLED=true
```

### Key Operations
- `add_entity()` / `add_relation()`: Low-level graph writes
- `get_related_context(keywords)`: Retrieve entity neighbourhood for RAG enrichment
- `get_shareable_chunk_ids(contribution_types=None)`: Marketplace export — returns chunk IDs with `shareable=True`; optionally filter by `contribution_type`

### Entity Extraction
LLM-based pipeline (active):
- [src/workflows/knowledge/entity_extractor.py](../../../workflows/knowledge/entity_extractor.py) — `extract_entities_from_chunk()`, `run_backfill()`

Backfill existing chunks:
```bash
python -m src.workflows.knowledge.entity_extractor --max-chunks 0
```

### Schema Bootstrap
[src/backends/storage/graph/neo4j_schema.py](../graph/neo4j_schema.py) — `ensure_schema(driver)` creates all constraints and indexes idempotently at startup (Neo4j ≥ 4.4).

### Related Files
- [src/backends/storage/graph/neo4j_repository.py](../graph/neo4j_repository.py)
- [src/backends/storage/graph/neo4j_schema.py](../graph/neo4j_schema.py)
- [src/workflows/knowledge/entity_extractor.py](../../../workflows/knowledge/entity_extractor.py)

## 3. Cache - SQLite Control Plane

**Purpose**: Lightweight persistence for operational metadata (no external cache).

**Location**: [src/backends/storage/sqlite/](../sqlite/)

### Features
- Scan checkpointing and resumibility
- File metadata and processing status
- Chunk registry and idempotence
- Temporal file tracking
- Memory checkpoints

### Configuration
```bash
CONTROL_PLANE_DB_PATH=./data/control_plane.db
```

## Storage Interfaces

Internal storage backends (vector, graph, cache) implement low-level
interfaces under `src/workflows/query/interfaces/`:

- [cache_interface.py](../../../../src/workflows/query/interfaces/cache_interface.py): Caching operations
- [graph_interface.py](../../../../src/workflows/query/interfaces/graph_interface.py): Graph operations
- [vector_interface.py](../../../../src/workflows/query/interfaces/vector_interface.py): Vector operations

## Pluggable Query Sources

Distinct from storage backends, **query sources** are external stores that
the RAG orchestrator consults at query time to retrieve knowledge.  They are
defined by two interfaces in `src/workflows/query/interfaces/query_source_interface.py`:

| Interface | Use case | Examples |
|---|---|---|
| `QuerySourceInterface` | Read-only sources managed externally or derived from Weaviate | Weaviate, Neo4j |
| `WritableQuerySourceInterface` | Sources the RAG pipeline also populates | MongoDB, pgvector/Postgres |

Concrete implementations live in `src/workflows/query/sources/`.  Each
source can be enabled or disabled at runtime via its `enabled` property
without restarting the service.  Ingestion into each store is handled by
the ingestion pipeline independently — query sources are query-time only.

## Data Flow Example

Typical ingestion flow through storage backends:

```
1. Document uploaded
   ↓
2. Process document (loader → chunker)
   ↓
3. Store chunks → Weaviate (vector embeddings)
   ↓
4. Extract entities (LLM) → Neo4j (Chunk, Entity, Topic, Source nodes)
   ↓
5. Checkpointing → SQLite control plane (file hash, stage tracking)
```

## Performance Considerations

### Weaviate
- **Optimal for**: Similarity search, nearest neighbor
- **Index type**: HNSW (tunable ef parameter)
- **Scaling**: Horizontal scaling via sharding

### Neo4j
- **Optimal for**: Graph traversals, relationship queries
- **Index**: Automatic indexing on node properties
- **Scaling**: Causal clustering for read replicas

### SQLite control plane
- **Optimal for**: Local metadata, context checkpoint compaction, and lightweight cache emulation
- **Persistence**: Built-in WAL-mode durability of `data/control_plane.db`
- **Scaling**: Single-node durability; rely on SQLite tooling for backups and vacuum

## Monitoring and Maintenance

### Health Checks
- Weaviate: `GET /v1/.well-known/ready`
- Neo4j: `CALL dbms.components()`
- SQLite control plane: `sqlite3 data/control_plane.db "PRAGMA quick_check;"`

### Backup Strategies
- **Weaviate**: Snapshot-based backups
- **Neo4j**: `neo4j-admin backup`
- **SQLite control plane**: Copy `data/control_plane.db` (and its WAL files) to your archive location; run `sqlite3 data/control_plane.db "VACUUM;"` before the copy when compaction is needed

## Related Documentation

- [RAG Interfaces](../../rag/interfaces/): Interface definitions
- [Provider Architecture](../../providers/doc/PROVIDERS_ARCHITECTURE.md): Provider system
- [Ingestion Documentation](../../ingestion/doc/): Ingestion pipeline
