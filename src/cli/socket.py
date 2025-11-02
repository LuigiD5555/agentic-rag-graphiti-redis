"""Module for the RAG socket server."""
import os
import socket
from src.config.settings import Config
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.providers.lmstudio.client import LLMService
from src.storage.graph.neo4j_repository import Neo4jRepository
from src.cache.redis_cache import CacheService
from src.rag.engine import RAGEngine
from src.rag.agent import Agent
from src.vectorstores import get_vector_store


def main():
    cfg = Config()

    # LM Studio base
    mm = ModelManager(
        cfg.LMSTUDIO_API_ROOTS,
        require_live=cfg.LMSTUDIO_REQUIRE_SERVER,
    )

    embed = EmbeddingService(cfg, mm)
    chat = LLMService(cfg, mm)
    vector = get_vector_store(cfg)
    graph = Neo4jRepository(cfg)
    cache = CacheService(cfg)

    rag_engine = RAGEngine(embed, vector, graph, cache, chat)
    agent = Agent(rag_engine)

    host, port = "0.0.0.0", int(os.getenv("SOCKET_PORT", "5555"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, port))
        s.listen()
        print(f"RAG socket server listening on {host}:{port}")
        conn, addr = s.accept()
        print(f"Connected by {addr}")
        with conn:
            conn.sendall(b"Welcome to RAG CLI (type 'q' to exit)\n> ")
            while True:
                data = conn.recv(1024).decode().strip()
                if not data or data.lower() == "q":
                    break
                response = agent.run(data)
                conn.sendall(f"\nAnswer:\n{response}\n> ".encode())


if __name__ == "__main__":
    main()
