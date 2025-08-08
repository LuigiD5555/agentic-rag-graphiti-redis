"""Main application entrypoint for RAG(Retrieval-Augmented Generation) System."""
import sys
import os
import socket
from typing import Optional
from src import logger
from src.config import Config
from src.model_manager import ModelManager
from src.embeddings import EmbeddingService
from src.llm_client import LLMService
from src.vectorstore import VectorStoreService
from src.graph_store import GraphStoreService
from src.cache import CacheService
from src.ner_extraction import NERExtractor
from src.document_loader import DocumentIngestor
from src.rag_chain import RAGEngine
from src.agent import Agent


class RAGApplication:
    """
    RAG (Retrieval-Augmented Generation) Application
    """
    def __init__(self) -> None:
        self.config = Config()
        self.model_manager: Optional[ModelManager] = None
        self.embedding: Optional[EmbeddingService] = None
        self.llm: Optional[LLMService] = None
        self.vector: Optional[VectorStoreService] = None
        self.graph: Optional[GraphStoreService] = None
        self.cache: Optional[CacheService] = None
        self.ner: Optional[NERExtractor] = None
        self.ingestor: Optional[DocumentIngestor] = None
        self.agent: Optional[Agent] = None
        self.enable_ner: bool = False

    def check_services(self) -> None:
        """Check connection to Qdrant (VectorStore)."""
        if not self.vector or not self.vector.client:
            logger.error("VectorStoreService is not initialized or missing client.")
            sys.exit(1)

        try:
            collections = self.vector.client.get_collections()
            logger.info(
                "Connected to Qdrant. Available collections: %s",
                [c.name for c in collections.collections]
            )
        except (ConnectionError, AttributeError) as e:
            logger.error("Could not connect to Qdrant: %s", e)
            sys.exit(1)

    def init_rag(self, enable_ner: bool = False) -> None:
        """Initialize full RAG pipeline."""
        try:
            self.enable_ner = enable_ner
            api_root = self.config.LM_EMBED_URL.rstrip("/")
            if api_root.endswith("/v1/embeddings"):
                api_root = api_root.rsplit("/v1/embeddings", 1)[0]

            self.model_manager = ModelManager(api_root)
            self.embedding = EmbeddingService(self.config, self.model_manager)
            self.llm = LLMService(self.config, self.model_manager)
            self.vector = VectorStoreService(self.config)
            self.graph = GraphStoreService(self.config)
            self.cache = CacheService(self.config)

            self.check_services()

            self.ner = NERExtractor(self.llm, self.graph)
            self.ingestor = DocumentIngestor(self.embedding, self.vector, self.ner)
            rag_engine = RAGEngine(self.embedding, self.vector, self.graph, self.cache, self.llm)
            self.agent = Agent(rag_engine)
        except (ConnectionError, RuntimeError) as e:
            logger.error("Error initializing RAG pipeline: %s", e)
            self.ingestor = None
            self.agent = None

    def start_socket_server(self) -> None:
        """Start TCP socket server for external host connection."""
        if not self.agent:
            logger.error("Agent is not initialized.")
            sys.exit(1)

        host = "0.0.0.0"
        port = int(os.getenv("SOCKET_PORT", "5555"))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            s.listen(1)
            print(f"Socket server listening on {host}:{port}")
            conn, addr = s.accept()
            print(f"Connected by {addr}")
            with conn:
                conn.sendall(b"Welcome to RAG CLI (type 'q' to exit)\n> ")
                while True:
                    data = conn.recv(1024).decode().strip()
                    if not data or data.lower() == "q":
                        break
                    response = self.agent.run(data)
                    conn.sendall(f"\nAnswer:\n{response}\n> ".encode())

    def handle_cli_mode(self, args) -> None:
        """Handle CLI modes: ingest, query, socket."""
        if not self.ingestor or not self.agent:
            logger.error("RAG pipeline components are not initialized.")
            sys.exit(1)

        if len(args) > 1:
            mode = args[1].lower()

            if mode == "--ingest":
                paths = args[2:]
                if not paths:
                    logger.warning("You must provide at least one path after --ingest")
                    return
                self.ingestor.ingest_multiple(paths)
                return

            if mode == "--query" and len(args) > 2:
                query = " ".join(args[2:])
                print("\nAnswer:\n" + self.agent.run(query))
                return

            if mode == "--socket":
                self.start_socket_server()
                return

            print("Invalid command. Use:")
            print("python -m src.main --ingest <path1> <path2> [--enable-er]")
            print("python -m src.main --query 'your question'")
            print("python -m src.main --socket")
            return

        # Interactive CLI if no arguments provided
        print("Hybrid RAG agent ready. Type your question (q to quit):")
        try:
            while True:
                query = input("> ")
                if query.lower() in ["q", "quit", "exit"]:
                    break
                response = self.agent.run(query)
                print(f"\nAnswer:\n{response}\n")
        except EOFError:
            logger.info("EOF detected. Exiting gracefully.")

    def run(self) -> None:
        """Main entrypoint for the RAG application."""
        enable_er = "--enable-er" in sys.argv
        if enable_er:
            sys.argv.remove("--enable-er")

        self.init_rag(enable_ner=enable_er)

        if not self.ingestor or not self.agent:
            logger.error("Failed to initialize RAG pipeline.")
            sys.exit(1)

        self.handle_cli_mode(sys.argv)


if __name__ == "__main__":
    app = RAGApplication()
    app.run()
