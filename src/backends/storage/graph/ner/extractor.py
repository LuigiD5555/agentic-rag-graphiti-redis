"""
NER extraction module.

Defines the NERExtractor class, which processes a single text input by sending it to a
Language Model (LLM) to identify named entities and relationships. The extracted data
is then inserted into a Neo4j graph database.

This module focuses exclusively on per-text extraction logic and graph insertion,
decoupled from embedding or ingestion workflows.
"""

from typing import Any, Dict, List
import json
from src import logger
from src.workflows.query.interfaces.chat_interface import ChatInterface
from src.workflows.query.interfaces.ner_interface import NERRepository


class NERExtractor:
    """
    Extracts named entities and relationships from text using a Language Model (LLM),
    and inserts them into a graph-based repository.
    """

    def __init__(self, llm_service: ChatInterface, ner_repo: NERRepository):
        """
        Initialize the NERExtractor with required services.

        Args:
            llm_service (ChatInterface): Service that provides LLM completions.
            ner_repo (NERRepository): Repository interface for inserting entities and relations.
        """
        self.llm = llm_service
        self.repo = ner_repo

    def extract_and_insert(self, text: str) -> None:
        """
        Extract entities and relationships from the input text using the LLM,
        and insert them into the graph repository.

        Args:
            text (str): Input text to analyze.
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
        result = self.llm.complete(prompt)
        if not result:
            logger.warning("NER extraction failed: LLM returned empty response.")
            return

        data = self._safe_parse_json(result)
        if isinstance(data, list):
            data = {"entities": data, "relations": []}
        elif not isinstance(data, dict):
            data = {"entities": [], "relations": []}

        entities = data.get("entities", [])
        relations = data.get("relations", [])
        if not isinstance(entities, list) or not isinstance(relations, list):
            logger.warning("Invalid JSON structure: expected 'entities' and 'relations' lists.")
            return

        self._insert_entities(entities)
        self._insert_relations(relations)

    def _safe_parse_json(self, raw: str) -> Dict[str, Any]:
        """
        Safely parse a JSON string and return a default structure on failure.

        Args:
            raw (str): Raw JSON string to parse.

        Returns:
            Dict[str, Any]: Parsed JSON object or default empty structure.
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON. Using empty structure.")
            return {"entities": [], "relations": []}

    def _insert_entities(self, entities: List[Dict[str, Any]]) -> None:
        """
        Insert extracted entities into the graph repository.

        Args:
            entities (List[Dict[str, Any]]): List of entity dictionaries with 'name' and 'type'.
        """
        for entity in entities:
            name = entity.get("name")
            type_ = entity.get("type", "Entity")
            if not name:
                logger.warning("Skipping entity with missing 'name': %s", entity)
                continue

            try:
                self.repo.add_entity(name, type_)
            except (ValueError, TypeError) as ex:
                logger.error("Failed to insert entity '%s': %s", name, ex)

    def _insert_relations(self, relations: List[Dict[str, Any]]) -> None:
        """
        Insert extracted relationships into the graph repository.

        Args:
            relations (List[Dict[str, Any]]): List of relation dictionaries
            with 'src', 'rel', and 'dst'.
        """
        for relation in relations:
            src, rel, dst = relation.get("src"), relation.get("rel"), relation.get("dst")
            if not (src and rel and dst):
                logger.warning("Skipping relation with missing fields: %s", relation)
                continue

            try:
                self.repo.add_relation(src, rel, dst)
            except (ValueError, TypeError) as ex:
                logger.error("Failed to insert relation '%s' (%s -> %s): %s", rel, src, dst, ex)
