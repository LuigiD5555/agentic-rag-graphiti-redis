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

**Purpose**: Knowledge graph for entity relationships and graph queries

**Location**: [src/storage/graph/neo4j_repository.py](../graph/neo4j_repository.py)

### Features
- Stores entities and relationships extracted via NER
- Cypher query language for complex graph traversals
- Relationship inference and graph analytics
- Path finding and pattern matching

### Configuration
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

### Use Cases
- Entity relationship discovery
- Knowledge graph queries
- Contextual entity retrieval
- Graph-based reasoning

### Entity Extraction
NER (Named Entity Recognition) pipeline (legacy/experimental):
- [src/storage/graph/legacy_ner/extractor.py](../graph/legacy_ner/extractor.py)
- [src/storage/graph/legacy_ner/bulk_runner.py](../graph/legacy_ner/bulk_runner.py)

### Related Files
- [src/storage/graph/neo4j_repository.py](../graph/neo4j_repository.py)
- [src/storage/graph/null_repository.py](../graph/null_repository.py) (stub for testing)

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
2. Process document
   ↓
4. Extract entities → Neo4j (graph)
   ↓
5. Generate embeddings → Check SQLite control plane (embedding cache metadata, context checkpoint compaction)
   ↓ (cache miss)
6. Compute embeddings → Store metadata/results in SQLite
   ↓
7. Store embeddings → Weaviate (vector)
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
