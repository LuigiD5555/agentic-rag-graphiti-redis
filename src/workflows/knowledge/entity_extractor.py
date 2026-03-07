"""Entity extraction job: reads chunks from Weaviate and populates Neo4j knowledge layer.

Usage (one-off backfill):
    python -m src.workflows.knowledge.entity_extractor

Usage (integrated — called by ingestion pipeline after each batch):
    from src.workflows.knowledge.entity_extractor import extract_entities_from_chunk
    extract_entities_from_chunk(chunk_id, text, source, neo4j_repo, chat_service)

Graph model written (Layer 2):
    (:Chunk {chunk_id, source})
    (:Entity {key, name, entity_type})
    (:Topic  {name})
    (:Source {title, type, shareable, author})
    (:Chunk)-[:MENTIONS]->(:Entity)
    (:Entity)-[:RELATED_TO]->(:Entity)   # co-occurrence within same chunk
    (:Entity)-[:PART_OF]->(:Topic)
    (:Chunk)-[:ORIGINATED_FROM]->(:Source)

Shareable inference:
    pdf, epub, book           → shareable=False  (externally-copyrighted)
    conversation, note, chat  → shareable=True   (user-generated knowledge)
    unknown / anything else   → shareable=False  (conservative default)
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------
_EXTRACTION_SYSTEM = (
    "You are an entity extraction engine. "
    "Given a text chunk, extract the key named entities and their types. "
    "Return ONLY a JSON object with this exact schema — no prose, no markdown:\n"
    '{"entities": [{"name": "...", "type": "CONCEPT|PERSON|PLACE|TECHNOLOGY|METHOD|ORGANIZATION"}], '
    '"topic": "..."}\n'
    "Rules:\n"
    "- Extract at most 8 entities.\n"
    "- entity type must be one of: CONCEPT, PERSON, PLACE, TECHNOLOGY, METHOD, ORGANIZATION.\n"
    "- topic is a single short noun phrase (≤5 words) that best describes the chunk.\n"
    "- Respond with valid JSON only."
)

_EXTRACTION_USER = "Text chunk:\n{text}"


def _call_llm(chat_service, text: str) -> Optional[Dict[str, Any]]:
    """Ask the LLM to extract entities; return parsed dict or None on failure."""
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM},
        {"role": "user", "content": _EXTRACTION_USER.format(text=text[:2000])},
    ]
    try:
        raw = chat_service.chat(messages=messages, temperature=0.0, max_tokens=512)
    except Exception as exc:
        log.warning("LLM call failed during entity extraction: %s", exc)
        return None

    # Strip markdown fences if the model wrapped the JSON anyway
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Entity extraction: could not parse LLM JSON (%s): %.200s", exc, raw)
        return None


# ---------------------------------------------------------------------------
# Neo4j write helpers
# ---------------------------------------------------------------------------

def _upsert_chunk(session, chunk_id: str, source: str, contribution_type: str = "unknown") -> None:
    session.run(
        "MERGE (c:Chunk {chunk_id: $chunk_id}) "
        "SET c.source = $source, c.contribution_type = $contribution_type",
        chunk_id=chunk_id, source=source, contribution_type=contribution_type,
    )


def _upsert_entity(session, name: str, entity_type: str) -> str:
    """Upsert entity node; returns the key used."""
    key = f"{name.lower()}|{entity_type}"
    session.run(
        "MERGE (e:Entity {key: $key}) "
        "SET e.name = $name, e.entity_type = $entity_type",
        key=key, name=name, entity_type=entity_type,
    )
    return key


def _upsert_topic(session, topic: str) -> None:
    session.run(
        "MERGE (t:Topic {name: $name})",
        name=topic,
    )


def _link_chunk_mentions(session, chunk_id: str, entity_key: str) -> None:
    session.run(
        "MATCH (c:Chunk {chunk_id: $chunk_id}), (e:Entity {key: $key}) "
        "MERGE (c)-[:MENTIONS]->(e)",
        chunk_id=chunk_id, key=entity_key,
    )


def _link_entity_topic(session, entity_key: str, topic: str) -> None:
    session.run(
        "MATCH (e:Entity {key: $key}), (t:Topic {name: $topic}) "
        "MERGE (e)-[:PART_OF]->(t)",
        key=entity_key, topic=topic,
    )


def _link_entity_cooccurrence(session, keys: List[str]) -> None:
    """Create RELATED_TO edges between all pairs co-occurring in the same chunk."""
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            session.run(
                "MATCH (a:Entity {key: $k1}), (b:Entity {key: $k2}) "
                "MERGE (a)-[:RELATED_TO]->(b) "
                "MERGE (b)-[:RELATED_TO]->(a)",
                k1=k1, k2=k2,
            )


# ---------------------------------------------------------------------------
# Shareable inference
# ---------------------------------------------------------------------------

_CONTRIBUTION_MAP: Dict[str, str] = {
    "conversation":  "original",
    "note":          "original",
    "memo":          "original",
    "chat":          "ai_assisted",
    "user_upload":   "original",
    "pdf":           "citation",
    "epub":          "citation",
    "book":          "citation",
    "libro":         "citation",
    "docx":          "citation",
    "doc":           "citation",
    "ebook":         "citation",
}

_SHAREABLE_TYPES = frozenset({"conversation", "note", "memo", "chat"})
_NON_SHAREABLE_TYPES = frozenset(
    {"pdf", "epub", "libro", "book", "doc", "docx", "ebook", "user_upload"}
)


def _normalize_document_type(document_type: Optional[str]) -> str:
    """Normalize a raw type string for reliable lookups."""
    if not document_type:
        return ""
    return str(document_type).strip().lower()


def _document_type_from_metadata(metadata: Dict[str, Any]) -> Optional[str]:
    """Give priority to explicit document type metadata keys."""
    for key in ("document_type", "doc_type", "type"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _infer_contribution_type(document_type: Optional[str]) -> str:
    """Map a document type string to a contribution category.

    Returns one of: "original", "ai_assisted", "citation", "unknown".
    """
    normalized = _normalize_document_type(document_type)
    if not normalized:
        return "unknown"
    return _CONTRIBUTION_MAP.get(normalized, "unknown")


def _infer_shareable(document_type: Optional[str]) -> bool:
    """Return True only for explicitly user-generated document types.

    pdf/epub/libro and other unknown types are conservatively treated as
    non-shareable.  conversation/note/memo/chat are the only shareable types today.
    """
    normalized = _normalize_document_type(document_type)
    if normalized in _SHAREABLE_TYPES:
        return True
    if normalized in _NON_SHAREABLE_TYPES:
        return False
    return False


# ---------------------------------------------------------------------------
# Source provenance helpers
# ---------------------------------------------------------------------------

def _upsert_source(session, title: str, doc_type: str, shareable: bool, author: str = "") -> None:
    session.run(
        "MERGE (s:Source {title: $title}) "
        "SET s.type = $type, s.shareable = $shareable, s.author = $author",
        title=title, type=doc_type, shareable=shareable, author=author,
    )


def _link_chunk_source(session, chunk_id: str, title: str) -> None:
    session.run(
        "MATCH (c:Chunk {chunk_id: $chunk_id}), (s:Source {title: $title}) "
        "MERGE (c)-[:ORIGINATED_FROM]->(s)",
        chunk_id=chunk_id, title=title,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_entities_from_chunk(
    chunk_id: str,
    text: str,
    source: str,
    neo4j_repo: Any,
    chat_service: Any,
    document_type: Optional[str] = None,
    author: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Extract entities from one chunk and write them to Neo4j.

    Args:
        chunk_id: Weaviate UUID of the chunk.
        text: Chunk text to extract entities from.
        source: Source file path or identifier.
        neo4j_repo: Neo4jRepository instance.
        chat_service: LLM chat service.
        document_type: Document type string (e.g. "pdf", "conversation"). Used
            to infer shareability for the Source node.
        author: Optional author name to store on the Source node.
        metadata: Optional Weaviate chunk metadata (source, file_path,
            document_type) that can be used to resolve provenance.

    Returns:
        The number of entities written (0 on failure).
    """
    if not text or not text.strip():
        return 0

    parsed = _call_llm(chat_service, text)
    if not parsed:
        return 0

    entities = parsed.get("entities") or []
    topic = (parsed.get("topic") or "").strip()

    if not entities:
        return 0

    metadata = dict(metadata or {})
    resolved_document_type = document_type or _document_type_from_metadata(metadata)
    resolved_source = source or metadata.get("source") or metadata.get("file_path") or chunk_id
    if not resolved_source:
        resolved_source = chunk_id
    source_title = (
        metadata.get("file_path")
        or metadata.get("source")
        or resolved_source
        or chunk_id
    )
    if not source_title:
        source_title = chunk_id

    contribution_type = _infer_contribution_type(resolved_document_type)
    shareable = _infer_shareable(resolved_document_type)
    author_name = author or metadata.get("author")
    author_name = str(author_name) if author_name else ""

    try:
        with neo4j_repo.driver.session() as session:
            _upsert_chunk(session, chunk_id, resolved_source, contribution_type)

            # Provenance: Source node + ORIGINATED_FROM link
            _upsert_source(
                session,
                title=source_title,
                doc_type=(resolved_document_type or "unknown").lower(),
                shareable=shareable,
                author=author_name,
            )
            _link_chunk_source(session, chunk_id, source_title)

            if topic:
                _upsert_topic(session, topic)

            entity_keys = []
            for ent in entities:
                name = (ent.get("name") or "").strip()
                etype = (ent.get("type") or "CONCEPT").strip().upper()
                if not name:
                    continue
                key = _upsert_entity(session, name, etype)
                entity_keys.append(key)
                _link_chunk_mentions(session, chunk_id, key)
                if topic:
                    _link_entity_topic(session, key, topic)

            _link_entity_cooccurrence(session, entity_keys)

        log.debug(
            "Extracted %d entities from chunk %s (topic=%s, shareable=%s)",
            len(entity_keys), chunk_id, topic, shareable,
        )
        return len(entity_keys)

    except Exception as exc:
        log.error("Failed to write entities for chunk %s: %s", chunk_id, exc)
        return 0


def run_backfill(
    weaviate_client: Any,
    collection_name: str,
    tenant: Optional[str],
    neo4j_repo: Any,
    chat_service: Any,
    batch_size: int = 256,
    max_chunks: int = 0,
) -> Dict[str, int]:
    """Backfill knowledge graph from all existing Weaviate chunks.

    Args:
        weaviate_client: Connected Weaviate client.
        collection_name: Weaviate collection to scan.
        tenant: Optional tenant ID for multi-tenancy.
        neo4j_repo: Neo4jRepository instance.
        chat_service: LLM chat service for entity extraction.
        batch_size: Weaviate pagination batch size.
        max_chunks: Stop after this many chunks (0 = unlimited).

    Returns:
        {"processed": N, "entities_written": M, "errors": K}
    """
    import weaviate as _weaviate  # local import to avoid hard dep at module level

    coll = weaviate_client.collections.get(collection_name)
    if tenant:
        coll = coll.with_tenant(tenant)

    stats = {"processed": 0, "entities_written": 0, "errors": 0}
    cursor: Optional[str] = None

    log.info(
        "Starting Neo4j knowledge backfill: collection=%s, tenant=%s, max=%s",
        collection_name, tenant, max_chunks or "unlimited",
    )

    while True:
        try:
            result = coll.query.fetch_objects(limit=batch_size, after=cursor)
        except Exception as exc:
            log.error("Weaviate fetch failed: %s", exc)
            stats["errors"] += 1
            break

        objects = getattr(result, "objects", []) or []
        if not objects:
            break

        for obj in objects:
            props = getattr(obj, "properties", {}) or {}
            chunk_id = str(getattr(obj, "uuid", ""))
            text = props.get("text", "")
            source_value = props.get("source") or props.get("file_path") or ""
            doc_type = props.get("document_type") or props.get("doc_type") or props.get("type")
            metadata: Dict[str, Any] = dict(props)
            if doc_type and not metadata.get("document_type"):
                metadata["document_type"] = doc_type

            written = extract_entities_from_chunk(
                chunk_id=chunk_id,
                text=text,
                source=source_value or chunk_id,
                neo4j_repo=neo4j_repo,
                chat_service=chat_service,
                metadata=metadata,
                author=metadata.get("author"),
            )

            stats["processed"] += 1
            stats["entities_written"] += written
            if written == 0 and text:
                stats["errors"] += 1

            if max_chunks and stats["processed"] >= max_chunks:
                log.info("Reached max_chunks=%d, stopping backfill", max_chunks)
                return stats

        last_uuid = getattr(objects[-1], "uuid", None)
        if last_uuid is None or len(objects) < batch_size:
            break
        cursor = str(last_uuid)

    log.info(
        "Backfill complete: processed=%d, entities_written=%d, errors=%d",
        stats["processed"], stats["entities_written"], stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from src.workflows.query.conf import Config
    from src.backends.llm.factory import ProviderFactory
    from src.backends.storage.graph.neo4j_repository import Neo4jRepository
    import weaviate

    parser = argparse.ArgumentParser(description="Backfill Neo4j knowledge graph from Weaviate chunks")
    parser.add_argument("--max-chunks", type=int, default=0, help="Max chunks to process (0=all)")
    parser.add_argument("--batch-size", type=int, default=256, help="Weaviate fetch batch size")
    args = parser.parse_args()

    cfg = Config()

    wc = weaviate.connect_to_local(
        host=cfg.WEAVIATE_URL.replace("http://", "").split(":")[0],
        port=int(cfg.WEAVIATE_URL.split(":")[-1]) if ":" in cfg.WEAVIATE_URL else 8080,
        grpc_port=cfg.WEAVIATE_GRPC_PORT,
    )
    neo4j = Neo4jRepository(cfg)
    provider = ProviderFactory(cfg)
    chat = provider.chat()

    try:
        result = run_backfill(
            weaviate_client=wc,
            collection_name=cfg.WEAVIATE_CLASS,
            tenant=cfg.WEAVIATE_DEFAULT_TENANT if cfg.WEAVIATE_MULTI_TENANCY else None,
            neo4j_repo=neo4j,
            chat_service=chat,
            batch_size=args.batch_size,
            max_chunks=args.max_chunks,
        )
        print(result)
    finally:
        wc.close()
        neo4j.close()
