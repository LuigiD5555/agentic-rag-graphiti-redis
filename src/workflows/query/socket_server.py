"""Module that implements a TCP socket server to handle RAG agent queries."""
import socket
from typing import Any


class SocketServer:
    """
    TCP Socket server to handle RAG agent queries.
    """

    def __init__(self, agent: Any, host: str = "0.0.0.0", port: int = 5555) -> None:
        self.agent = agent
        self.host = host
        self.port = port

    def start(self) -> None:
        """
        Start the socket server and handle incoming client connections.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind((self.host, self.port))
            server_socket.listen(1)
            print(f"Listening on {self.host}:{self.port}")

            conn, addr = server_socket.accept()
            print(f"Connected by {addr}")

            with conn:
                conn.sendall(b"Welcome to RAG CLI\nType your question (q to quit)\n> ")
                while True:
                    data = conn.recv(1024).decode().strip()
                    if not data or data.lower() == "q":
                        break
                    response = self.agent.run(data)
                    conn.sendall(f"{response}\n> ".encode())
