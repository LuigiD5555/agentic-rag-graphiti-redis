# Storage Documentation

This directory contains documentation for storage backends.

## Contents

- [STORAGE_BACKENDS.md](STORAGE_BACKENDS.md) - Overview of all storage backends

## Storage Components

### Vector Store
- **Weaviate**: Primary vector database
- Location: [src/storage/vector/weaviate_repository/](../vector/weaviate_repository/)

### Graph Store
- **Neo4j**: Knowledge graph storage
- Location: [src/storage/graph/neo4j_repository.py](../graph/neo4j_repository.py)

### Cache
- **SQLite control plane**: Local cache/checkpoint storage (context checkpoint compaction, metadata, resumable scans, no external cache dependency).
- Location: [src/backends/storage/sqlite/](../sqlite/)

## Related Documentation

- General project documentation: [../../../docs/](../../../docs/)
- Provider documentation: [../../providers/doc/](../../providers/doc/)
