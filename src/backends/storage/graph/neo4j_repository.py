"""Module with services that interact with a Neo4j database."""
import re
from typing import Optional, cast, LiteralString, Dict, Any, List
from neo4j import GraphDatabase, Query
from neo4j.exceptions import Neo4jError
from src import logger
from src.core import Result
from src.core.errors import GraphError


# Validators
def validate_label(label: str) -> str:
    """Ensure label is a safe and valid Cypher identifier (PascalCase)."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", label):
        raise ValueError(f"Invalid label: {label}")
    return label


def validate_relation(rel: str) -> str:
    """Ensure relation type is uppercase and safe (UPPER_SNAKE_CASE)."""
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", rel):
        raise ValueError(f"Invalid relation: {rel}")
    return rel


# Safe Query Helper
def safe_query(cypher: str) -> Query:
    """
    Convert a validated dynamic string into a Query object.
    Uses cast to satisfy Pylance since Query expects LiteralString.
    """
    return Query(cast(LiteralString, cypher))


# Main Service
class Neo4jRepository:
    """Service for managing graph data in Neo4j."""
    def __init__(self, config):
        """Initialize Neo4j driver with provided configuration."""
        try:
            self.driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
            )
            logger.info("Neo4j driver initialized successfully.")
        except Neo4jError as e:
            logger.error("Failed to initialize Neo4j driver: %s", e)
            raise

    def close(self):
        """Close Neo4j driver connection safely."""
        try:
            self.driver.close()
            logger.info("Neo4j driver connection closed.")
        except Neo4jError as e:
            logger.warning("Error while closing Neo4j driver: %s", e)

    # Entity Methods
    def add_entity(
        self, name: str,
        entity_type: str = "Entity",
        properties: Dict[str, Any] | None = None
    ) -> None:
        """
        Create or merge an entity node with the given label and properties.
        """
        if not name:
            raise ValueError("Entity name cannot be empty.")

        try:
            label = validate_label(entity_type)

            cypher = f"""
            MERGE (e:{label} {{name: $name}})
            SET e += $props
            """

            with self.driver.session() as session:
                session.run(safe_query(cypher), name=name, props=properties or {})

            logger.info("Entity '%s' of type '%s' added successfully.", name, label)

        except (Neo4jError, ValueError) as e:
            logger.error("Error adding entity '%s': %s", name, e)
            raise

    # Relation Methods
    def add_relation(self, src: str, rel: str, dst: str, properties: Optional[dict] = None):
        """
        Create or merge a relationship between two entities.
        """
        if not src or not dst:
            raise ValueError("Relation source and destination cannot be empty.")

        try:
            relation = validate_relation(rel)

            cypher = f"""
            MATCH (a {{name: $src}}), (b {{name: $dst}})
            MERGE (a)-[r:{relation}]->(b)
            SET r += $props
            """

            with self.driver.session() as session:
                session.run(safe_query(cypher), src=src, dst=dst, props=properties or {})

            logger.info("Relation '%s' created between '%s' and '%s'.", relation, src, dst)

        except (Neo4jError, ValueError) as e:
            logger.error("Error creating relation '%s' from '%s' to '%s': %s", rel, src, dst, e)
            raise

    # Protocol-Compatible Search
    def search(self, query: str) -> list[str]:
        """
        Method compatible with GraphStoreProtocol.
        Defaults to include_reverse=True.
        """
        return self._search_internal(query)

    # Internal search logic
    def _search_internal(self, keyword: str, include_reverse: bool = True) -> list[str]:
        """
        Search for nodes and relationships matching a keyword.
        Returns readable strings: "NodeA -[RELATION]-> NodeB"
        """
        try:
            if include_reverse:
                cypher = """
                MATCH (e)-[r]-(x)
                WHERE e.name CONTAINS $kw OR x.name CONTAINS $kw
                RETURN e.name AS source, type(r) AS relation, x.name AS target
                """
            else:
                cypher = """
                MATCH (e)-[r]->(x)
                WHERE e.name CONTAINS $kw OR x.name CONTAINS $kw
                RETURN e.name AS source, type(r) AS relation, x.name AS target
                """

            with self.driver.session() as session:
                result = session.run(safe_query(cypher), kw=keyword)
                matches = [
                    f"{record['source']} -[{record['relation']}]-> {record['target']}"
                    for record in result
                ]

            logger.info("Search for keyword '%s' returned %d results.", keyword, len(matches))
            return matches

        except Neo4jError as e:
            logger.error("Search failed for keyword '%s': %s", keyword, e)
            raise

    def get_related_context(
        self,
        keywords: List[str],
        max_hops: int = 1,
        limit: int = 40,
    ) -> "Result[List[Dict[str, Any]], GraphError]":
        """Return entity neighbourhood for the given keywords.

        Walks up to *max_hops* away from any Entity whose name matches one of
        the keywords (case-insensitive substring match).  Returns a list of
        dicts, each describing one relationship edge:
            {"source": str, "source_type": str,
             "relation": str,
             "target": str, "target_type": str,
             "topic": str | None}

        This is used by the RAG orchestrator to inject structured graph
        context alongside the Weaviate text chunks.

        Returns:
            Result[list[dict], GraphError] — Ok with edges, or Err with cause.
        """
        if not keywords:
            return Result.ok([])

        kw_lower = [k.lower() for k in keywords if k.strip()]
        if not kw_lower:
            return Result.ok([])

        cypher = """
        UNWIND $keywords AS kw
        MATCH (e:Entity)
        WHERE toLower(e.name) CONTAINS kw
        WITH DISTINCT e
        MATCH (e)-[r:RELATED_TO|PART_OF]->(n)
        OPTIONAL MATCH (e)-[:PART_OF]->(t:Topic)
        RETURN
            e.name        AS source,
            e.entity_type AS source_type,
            type(r)       AS relation,
            n.name        AS target,
            labels(n)[0]  AS target_type,
            t.name        AS topic
        LIMIT $limit
        """

        try:
            with self.driver.session() as session:
                result = session.run(
                    safe_query(cypher),
                    keywords=kw_lower,
                    limit=limit,
                )
                rows = [
                    {
                        "source": record["source"],
                        "source_type": record["source_type"],
                        "relation": record["relation"],
                        "target": record["target"],
                        "target_type": record["target_type"],
                        "topic": record["topic"],
                    }
                    for record in result
                ]
            logger.info(
                "get_related_context: keywords=%s returned %d edges",
                keywords, len(rows),
            )
            return Result.ok(rows)
        except Neo4jError as exc:
            return Result.err(GraphError("get_related_context", str(exc), cause=exc))

    def get_shareable_chunks(
        self,
        contribution_types: Optional[List[str]] = None,
    ) -> "Result[List[str], GraphError]":
        """Return IDs of chunks whose Source is marked shareable=True.

        Args:
            contribution_types: If provided, further filter by chunk
                contribution_type (e.g. ["original", "ai_assisted"]).
                When None, all shareable chunks are returned regardless of type.

        Returns:
            Result[list[str], GraphError] — Ok with chunk IDs, or Err with cause.
        """
        if contribution_types:
            cypher = """
            MATCH (c:Chunk)-[:ORIGINATED_FROM]->(s:Source {shareable: true})
            WHERE c.contribution_type IN $types
            RETURN c.chunk_id AS chunk_id
            """
            params: Dict[str, Any] = {"types": contribution_types}
        else:
            cypher = """
            MATCH (c:Chunk)-[:ORIGINATED_FROM]->(s:Source {shareable: true})
            RETURN c.chunk_id AS chunk_id
            """
            params = {}

        try:
            with self.driver.session() as session:
                result = session.run(safe_query(cypher), **params)
                ids = [record["chunk_id"] for record in result if record["chunk_id"]]
            logger.info("get_shareable_chunks: returned %d chunk IDs", len(ids))
            return Result.ok(ids)
        except Neo4jError as exc:
            return Result.err(GraphError("get_shareable_chunks", str(exc), cause=exc))

    get_shareable_chunk_ids = get_shareable_chunks
