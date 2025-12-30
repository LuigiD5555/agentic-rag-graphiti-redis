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
┌───▼────┐     ┌─────▼──────┐    ┌────▼─────┐
│Weaviate│     │   Neo4j    │    │ Redis    │
│(Vector)│     │  (Graph)   │    │(Cache)   │
└────────┘     └────────────┘    └──────────┘
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

## 3. Cache - Redis

**Purpose**: High-performance caching layer

**Location**: [src/storage/cache/](../cache/)

### Features
- Embedding cache (avoid re-computing embeddings)
- Ingestion cache (file discovery, hash tracking)
- Session cache
- Rate limiting

### Configuration
```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
```

### Cache Types

#### Embedding Cache
- Location: [src/storage/cache/redis_cache.py](../cache/redis_cache.py)
- TTL: 7 days (configurable via `RAG_EMBED_CACHE_TTL`)
- Prefix: `embed:` (configurable via `RAG_EMBED_CACHE_PREFIX`)

#### Ingestion Cache
- Location: [src/storage/cache/ingestion/](../cache/ingestion/)
- Components:
  - [file_cache.py](../cache/ingestion/file_cache.py): File hash tracking
  - [directory_cache.py](../cache/ingestion/directory_cache.py): Directory discovery cache
  - [manager.py](../cache/ingestion/manager.py): Cache coordination

### Related Files
- [src/storage/cache/redis_connection.py](../cache/redis_connection.py)
- [src/storage/cache/redis_cache.py](../cache/redis_cache.py)
- [src/storage/cache/ingestion/](../cache/ingestion/)

## Storage Interfaces

All storage backends implement standardized interfaces defined in [src/rag/interfaces/](../../rag/interfaces/):

- [cache_interface.py](../../rag/interfaces/cache_interface.py): Caching operations
- [graph_interface.py](../../rag/interfaces/graph_interface.py): Graph operations
- [vector_interface.py](../../rag/interfaces/vector_interface.py): Vector operations
- [storage_plugin_interface.py](../../rag/interfaces/storage_plugin_interface.py): Plugin system

## Data Flow Example

Typical ingestion flow through storage backends:

```
1. Document uploaded
   ↓
2. Check Redis cache (file hash)
   ↓ (cache miss)
3. Process document
   ↓
4. Extract entities → Neo4j (graph)
   ↓
5. Generate embeddings → Check Redis (embedding cache)
   ↓ (cache miss)
6. Compute embeddings → Store in Redis
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

### Redis
- **Optimal for**: Sub-millisecond reads/writes
- **Persistence**: RDB snapshots + AOF
- **Scaling**: Redis Cluster for partitioning

## Monitoring and Maintenance

### Health Checks
- Weaviate: `GET /v1/.well-known/ready`
- Neo4j: `CALL dbms.components()`
- Redis: `PING`

### Backup Strategies
- **Weaviate**: Snapshot-based backups
- **Neo4j**: `neo4j-admin backup`
- **Redis**: RDB + AOF persistence

## Related Documentation

- [RAG Interfaces](../../rag/interfaces/): Interface definitions
- [Provider Architecture](../../providers/doc/PROVIDERS_ARCHITECTURE.md): Provider system
- [Ingestion Documentation](../../ingestion/doc/): Ingestion pipeline
