"""Module for the RAG socket server."""
import os
import socket
from src.rag.conf import Config
from src.providers.factory import ProviderFactory
from src.storage.graph import get_graph_store
from src.storage.cache import get_cache
from src.rag.engine import RAGEngine
from src.rag.cli.agent import Agent
from src.storage.vector import get_vector_store
from src.rag.embeddings_factory import get_embedding_service


def main():
    cfg = Config()

    provider = ProviderFactory(cfg)
    embed = get_embedding_service(cfg, provider)
    chat = provider.chat()
    vector = get_vector_store(cfg)
    graph = get_graph_store(cfg)
    cache = get_cache(cfg)

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
