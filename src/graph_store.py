"""Module with services that interact with a Neo4j database."""
import re
from typing import Optional, cast, LiteralString
from neo4j import GraphDatabase, Query
from neo4j.exceptions import Neo4jError
from src import logger


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
class GraphStoreService:
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
    def add_entity(self, name: str, entity_type: str = "Entity", properties: Optional[dict] = None):
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
