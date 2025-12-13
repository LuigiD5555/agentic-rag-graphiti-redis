"""
Bulk NER processing module.

This module defines the NERBulkProcessor class, which orchestrates the extraction
of named entities and relationships from pre-embedded content stored in the vector DB,
and inserts them into a Neo4j graph database using a Language Model.
"""

from json import JSONDecodeError
from neo4j.exceptions import Neo4jError
from requests import RequestException
from src import logger
from src.settings import Config
from src.providers.factory import ProviderFactory
from src.storage.graph import get_graph_store
from src.storage.graph.ner.extractor import NERExtractor
from src.storage.vector import get_vector_store


class NERBulkProcessor:
    """
    Process payloads in batches from the vector store and enrich the graph.
    """

    def __init__(self, batch_size: int = 256, only_text: bool = False, only_code: bool = False):
        """
        Args:
            batch_size (int): Batch size for iterating payloads.
            only_text (bool): If True, process only text-type payloads.
            only_code (bool): If True, process only code-type payloads.
        """
        self.batch_size = batch_size
        self.only_text = only_text
        self.only_code = only_code

        cfg = Config()
        provider = ProviderFactory(cfg)
        self.llm = provider.chat()
        self.vector = get_vector_store(cfg)
        self.ner_repo = get_graph_store(cfg)
        self.extractor = NERExtractor(self.llm, self.ner_repo)

    def _iter_payloads(self):
        """
        Internal generator to iterate over payloads in batches from the vector store.
        """
        for payload in self.vector.iter_payloads(batch_size=self.batch_size):
            yield payload

    def _process_payload(self, payload: dict) -> bool:
        """
        Process a single payload: apply filters and run NER.
        """
        is_code = payload.get("type") == "code"
        is_text = not is_code

        if self.only_code and not is_code:
            return False
        if self.only_text and not is_text:
            return False

        content = payload.get("content") or payload.get("structure_summary")
        if not content:
            return False

        try:
            self.extractor.process_text(content, payload)
            return True
        except (RequestException, JSONDecodeError, Neo4jError) as e:
            logger.error("NER processing error for payload %s: %s", payload.get("external_id") or payload.get("hash"), e)
            return False

    def run(self) -> None:
        """
        Run the bulk NER processing.
        """
        total = 0
        ok = 0
        for payload in self._iter_payloads():
            total += 1
            if self._process_payload(payload):
                ok += 1
        logger.info("NER bulk done. Processed=%d, Success=%d", total, ok)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run NER in bulk from vector payloads")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--only-text", action="store_true")
    parser.add_argument("--only-code", action="store_true")
    args = parser.parse_args()

    processor = NERBulkProcessor(
        batch_size=args.batch_size,
        only_text=args.only_text,
        only_code=args.only_code
    )
    processor.run()
