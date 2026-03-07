"""Neo4j schema bootstrap — constraints and indexes for the dual-layer data model.

Dual-layer model
----------------
Layer 1 — Filtering (access control / installation topology):
    (:Installation)-[:HAS_GROUP]->(:Group)-[:HAS_EMBEDDING]->(:Embedding)

Layer 2 — Knowledge graph (RAG enrichment):
    (:Chunk)-[:MENTIONS]->(:Entity)
    (:Entity)-[:RELATED_TO]->(:Entity)
    (:Entity)-[:PART_OF]->(:Topic)
    (:Chunk)-[:ORIGINATED_FROM]->(:Source)
    (:Chunk)-[:OWNED_BY]->(:User)

Source node tracks provenance and shareability for marketplace export:
    shareable=True  → conversation, note (knowledge created by the user)
    shareable=False → pdf, epub, book (externally-copyrighted material)

Each Source node stores `title`, `type`, `shareable`, and `author` so exports can make whitelisting
decisions quickly.  User nodes expose `user_id` to keep OWNED_BY relationships resolvable.

Call ``ensure_schema(driver)`` once at startup.  It is idempotent — safe to
call on every boot; existing constraints/indexes are left untouched.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import Driver

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constraint definitions
# Each entry: (constraint_name, label, property)
# ---------------------------------------------------------------------------
_UNIQUENESS_CONSTRAINTS = [
    # Layer 1 — filtering
    ("uniq_installation_id",  "Installation", "id"),
    ("uniq_group_id",         "Group",        "id"),
    ("uniq_embedding_id",     "Embedding",    "id"),
    # Layer 2 — knowledge
    ("uniq_chunk_id",         "Chunk",        "chunk_id"),
    ("uniq_entity_name_type", "Entity",       "key"),   # key = name + "|" + type
    ("uniq_topic_name",       "Topic",        "name"),
    # Layer 2 — provenance
    ("uniq_source_title",     "Source",       "title"),
    ("uniq_user_id",          "User",         "user_id"),
]

# ---------------------------------------------------------------------------
# Index definitions (for fast lookups beyond the unique constraints)
# Each entry: (index_name, label, property)
# ---------------------------------------------------------------------------
_INDEXES = [
    # Layer 1
    ("idx_installation_name", "Installation", "name"),
    # Layer 2 — full-text-style property lookups
    ("idx_entity_name",       "Entity",       "name"),
    ("idx_entity_type",       "Entity",       "entity_type"),
    ("idx_chunk_source",      "Chunk",        "source"),
    ("idx_topic_name",        "Topic",        "name"),
    # Layer 2 — provenance (shareable needed for fast export queries)
    ("idx_source_shareable",         "Source", "shareable"),
    ("idx_source_type",              "Source", "type"),
    ("idx_chunk_contribution_type",  "Chunk",  "contribution_type"),
]


def ensure_schema(driver: "Driver") -> None:
    """Create constraints and indexes if they do not already exist.

    Idempotent — uses ``IF NOT EXISTS`` syntax (Neo4j ≥ 4.4).
    """
    with driver.session() as session:
        _apply_constraints(session)
        _apply_indexes(session)
    log.info("Neo4j schema bootstrap complete")


def _apply_constraints(session) -> None:
    for name, label, prop in _UNIQUENESS_CONSTRAINTS:
        cypher = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        try:
            session.run(cypher)
            log.debug("Constraint ensured: %s", name)
        except Exception as exc:
            # Older Neo4j versions (< 4.4) don't support IF NOT EXISTS — log
            # and continue rather than crashing the whole boot sequence.
            log.warning("Could not create constraint %s: %s", name, exc)


def _apply_indexes(session) -> None:
    for name, label, prop in _INDEXES:
        cypher = (
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.{prop})"
        )
        try:
            session.run(cypher)
            log.debug("Index ensured: %s", name)
        except Exception as exc:
            log.warning("Could not create index %s: %s", name, exc)


__all__ = ["ensure_schema"]
