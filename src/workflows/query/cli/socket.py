"""Module for the RAG socket server."""
import socket
from src.conf import settings
from src.backends.llm.factory import ProviderFactory
from src.backends.storage.graph import get_graph_store
from src.backends.storage.cache import get_cache
from src.workflows.query.engine import RAGEngine
from src.workflows.query.cli.agent import Agent
from src.backends.storage.vector import get_vector_store
from src.workflows.query.embeddings_factory import get_embedding_service


def main():
    provider = ProviderFactory(settings)
    embed = get_embedding_service(settings, provider, context="query")
    chat = provider.chat()
    vector = get_vector_store(settings)
    graph = get_graph_store(settings)
    cache = get_cache(settings)

    rag_engine = RAGEngine(
        embed,
        vector,
        graph,
        cache,
        chat,
        default_tenant=(settings.WEAVIATE_DEFAULT_TENANT or None),
    )
    agent = Agent(rag_engine)

    host, port = "0.0.0.0", settings.SOCKET_PORT
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
