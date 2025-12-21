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

### NoSQL Store
- **MongoDB**: Document storage
- Location: [src/storage/nosql/mongo_repository.py](../nosql/mongo_repository.py)

### SQL Store
- **PostgreSQL**: Relational data
- Location: [src/storage/sql/postgres_repository.py](../sql/postgres_repository.py)

### Cache
- **Redis**: Caching layer
- Location: [src/storage/cache/](../cache/)

## Related Documentation

- General project documentation: [../../../docs/](../../../docs/)
- Provider documentation: [../../providers/doc/](../../providers/doc/)
