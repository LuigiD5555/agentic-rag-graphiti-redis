"""Module for the RAG socket server."""
import os
import socket
from src.settings import Config
from src.providers.factory import ProviderFactory
from src.storage.graph.neo4j_repository import Neo4jRepository
from src.storage.cache import CacheService
from src.rag.engine import RAGEngine
from src.rag.cli.agent import Agent
from src.storage.vector import get_vector_store


def main():
    cfg = Config()

    provider = ProviderFactory(cfg)
    embed = provider.embeddings()
    chat = provider.chat()
    vector = get_vector_store(cfg)
    graph = Neo4jRepository(cfg)
    cache = CacheService(cfg)

    rag_engine = RAGEngine(
        embed,
        vector,
        graph,
        cache,
        chat,
        default_tenant=(cfg.WEAVIATE_DEFAULT_TENANT or None),
    )
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
