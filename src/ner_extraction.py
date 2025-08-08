"""
Module for Named Entity Recognition (NER) extraction and insertion into a
graph store using and Language Model (LM).
"""
import json
from typing import Any, Dict, List
from src import logger


class NERExtractor:
    """
    Extracts Named Entities and Relations from text using an LLM
    and inserts them into a graph store.
    """

    def __init__(self, llm_service, graph_store):
        """
        :param llm_service: Instance of LLMService with .complete(prompt) method
        :param graph_store: Instance of GraphStore with .add_entity and .add_relation
        """
        self.llm = llm_service
        self.graph = graph_store

    def extract_and_insert(self, text: str) -> None:
        """
        Generate entities and relations using the LLM and insert them into the graph.
        """
        prompt = f"""
        Extract entities and relationships from the following text in JSON format:
        {{
            "entities": [{{"name": "Entity", "type": "Type"}}],
            "relations": [{{"src": "Entity1", "rel": "RELATION", "dst": "Entity2"}}]
        }}
        Text:
        {text}
        """

        # Request completion
        result = self.llm.complete(prompt)

        if not result:
            logger.warning("ER extraction failed: LLM returned empty response.")
            return

        # Parse JSON safely
        data = self._safe_parse_json(result)

        # Handle unexpected formats: list or invalid dict
        if isinstance(data, list):
            # Interpret list as list of entities (no relations)
            data = {"entities": data, "relations": []}
        elif not isinstance(data, dict):
            # Force to valid dict if something unexpected
            data = {"entities": [], "relations": []}

        # Validate and extract entities/relations
        entities = data.get("entities", [])
        relations = data.get("relations", [])

        if not isinstance(entities, list) or not isinstance(relations, list):
            logger.warning("Invalid JSON structure: expected 'entities' and 'relations' lists.")
            return

        self._insert_entities(entities)
        self._insert_relations(relations)

    # Internal helpers
    def _safe_parse_json(self, raw: str) -> Dict[str, Any]:
        """Parse JSON string safely and fallback to empty structure on error."""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON. Using empty structure.")
            return {"entities": [], "relations": []}

    def _insert_entities(self, entities: List[Dict[str, Any]]) -> None:
        """Insert entities into the graph with error handling."""
        for entity in entities:
            name = entity.get("name")
            type_ = entity.get("type", "Entity")

            if not name:
                logger.warning("Skipping entity with missing 'name': %s", entity)
                continue

            try:
                self.graph.add_entity(name, type_)
            except (ValueError, TypeError) as e:
                logger.error("Failed to insert entity '%s': %s", name, e)

    def _insert_relations(self, relations: List[Dict[str, Any]]) -> None:
        """Insert relations into the graph with error handling."""
        for rel in relations:
            src = rel.get("src")
            relation = rel.get("rel")
            dst = rel.get("dst")

            if not (src and relation and dst):
                logger.warning("Skipping relation with missing fields: %s", rel)
                continue

            try:
                self.graph.add_relation(src, relation, dst)
            except (ValueError, TypeError) as e:
                logger.error(
                    "Failed to insert relation '%s' between '%s' and '%s': %s",
                    relation, src, dst, e
                )
