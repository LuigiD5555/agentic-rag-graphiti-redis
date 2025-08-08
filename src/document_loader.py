"""
Document loader and ingestor for multiple file types including PDFs, DOCX, XLSX,
TXT, Markdown, and code files like Python and JavaScript.
"""
import argparse
import hashlib
import os
import re
import uuid
from typing import Dict, List, Protocol

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    Docx2txtLoader, PyPDFLoader, TextLoader
)
from src import logger
from src.config import Config
from src.embeddings import EmbeddingService
from src.graph_store import GraphStoreService
from src.llm_client import LLMService
from src.model_manager import ModelManager
from src.ner_extraction import NERExtractor
from src.vectorstore import VectorStoreService


# Protocol definitions
class DocumentLoader(Protocol):
    def load(self) -> List[Document]:
        ...


class EmbeddingServiceProtocol(Protocol):
    def generate(self, text: str) -> List[float]:
        ...


class VectorStoreProtocol(Protocol):
    def upsert(self, key: str, vector: List[float], metadata: Dict[str, str]) -> None:
        ...


class NERExtractorProtocol(Protocol):
    def extract_and_insert(self, text: str) -> None:
        ...


class DocumentIngestor:
    """
    Handles ingestion of documents and code: loading, chunking,
    embedding generation, and storage in vector store and graph.
    Optionally performs Named Entity & Relation extraction (NER).
    """

    def __init__(
        self,
        embedding_service_: EmbeddingServiceProtocol,
        vector_store_service: VectorStoreProtocol,
        ner_extractor_service: NERExtractorProtocol,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        enable_ner: bool = False
    ) -> None:
        self.embedding = embedding_service_
        self.vector = vector_store_service
        self.ner = ner_extractor_service
        self.enable_ner = enable_ner
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

    def _normalize_path(self, path: str) -> str:
        """Normalize paths to handle multiple spaces (keep apostrophes intact)."""
        normalized = " ".join(path.split())
        return normalized

    def _clean_markdown(self, text: str) -> str:
        """Remove Markdown syntax like images and links."""
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return text

    def _extract_code_structure(self, code_text: str) -> str:
        """
        Extract high-level structure: functions, classes, methods.
        This prevents storing raw code, focusing on context.
        """
        lines = code_text.splitlines()
        structure = []
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("class "):
                structure.append(f"Line {i}: {stripped}")
        return "\n".join(structure) if structure else "File structure only"

    def _get_content_hash(self, text: str) -> str:
        """Generate a SHA256 hash for the given text to avoid duplicate inserts."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def ingest_multiple(self, paths: List[str]) -> None:
        """Ingest documents and code from multiple paths."""
        total_chunks = 0
        total_files = 0

        for path in paths:
            path = self._normalize_path(path)

            if not os.path.exists(path):
                logger.error("The folder '%s' does not exist.", path)
                continue

            files = []
            for root, _, filenames in os.walk(path):
                for f in filenames:
                    if f.endswith((".pdf", ".docx", ".txt", ".md", ".py", ".js")):
                        files.append(os.path.join(root, f))

            if not files:
                logger.warning("No supported documents or code found in '%s'.", path)
                continue

            for file in files:
                try:
                    file = self._normalize_path(file)

                    # Detect loader type
                    loader: DocumentLoader | None
                    if file.endswith(".pdf"):
                        loader = PyPDFLoader(file)
                    elif file.endswith(".docx"):
                        loader = Docx2txtLoader(file)
                    elif file.endswith((".txt", ".md")):
                        loader = TextLoader(file, encoding="utf-8")
                    else:
                        loader = None  # For code files

                    if loader:
                        # Document ingestion (text, markdown)
                        docs = loader.load()
                        for chunk in self.splitter.split_documents(docs):
                            text = chunk.page_content
                            if file.endswith(".md"):
                                text = self._clean_markdown(text)

                            # Generate hash for deduplication
                            content_hash = self._get_content_hash(text)

                            emb = self.embedding.generate(text)
                            # Generate valid UUID for Qdrant point ID
                            point_id = str(uuid.uuid4())
                            self.vector.upsert(point_id, emb, {
                                "source": file,
                                "content": text,
                                "hash": content_hash
                            })

                            if self.enable_ner:
                                self.ner.extract_and_insert(text)

                            total_chunks += 1
                    else:
                        # Code ingestion (summarized structure)
                        with open(file, "r", encoding="utf-8") as code_file:
                            code_text = code_file.read()

                        structure_summary = self._extract_code_structure(code_text)
                        content_hash = self._get_content_hash(structure_summary)
                        emb = self.embedding.generate(structure_summary)
                        # Generate valid UUID for code structure point ID
                        point_id = str(uuid.uuid4())
                        self.vector.upsert(
                            point_id,
                            emb,
                            {
                                "source": file,
                                "type": "code_context",
                                "structure_summary": structure_summary,
                                "hash": content_hash
                            }
                        )

                        if self.enable_ner:
                            self.ner.extract_and_insert(structure_summary)

                        total_chunks += 1

                    total_files += 1

                except (IOError, ValueError, RuntimeError) as e:
                    logger.error("Could not process '%s': %s", file, e)

        logger.info(
            "Indexed %d chunks from %d files (documents + code) into Qdrant and updated graph.",
            total_chunks,
            total_files
        )


# CLI entry point

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest documents and code into the vector database."
    )
    parser.add_argument(
        "--path",
        nargs="+",
        required=True,
        help="One or more absolute paths to directories containing documents or code."
    )
    parser.add_argument(
        "--enable-ner",
        action="store_true",
        help="Enable Named Entity & Relation extraction during ingestion"
    )
    args = parser.parse_args()

    # Initialize services
    config = Config()

    # Create instance of ModelManager
    API_ROOT = config.LM_EMBED_URL.rstrip("/")
    if API_ROOT.endswith("/v1/embeddings"):
        API_ROOT = API_ROOT.rsplit("/v1/embeddings", 1)[0]
    model_manager = ModelManager(API_ROOT)

    embedding_service = EmbeddingService(config, model_manager)
    vector_store = VectorStoreService(config)
    llm_service = LLMService(config, model_manager)
    graph_store = GraphStoreService(config)
    ner_extractor = NERExtractor(llm_service, graph_store)

    ingestor = DocumentIngestor(
        embedding_service,
        vector_store,
        ner_extractor,
        enable_ner=args.enable_ner
    )
    ingestor.ingest_multiple(args.path)
