"""Compatibility entrypoint: delegates to CLI modules."""
import sys
from src.cli.ingest import main as run_ingest
from src.cli.query import main as run_query
from src.cli.socket import main as run_socket


def main():
    """
    Main entry point for the RAG CLI.
    """
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode == "--ingest":
            sys.argv = ["ingest.py", "--paths"] + sys.argv[2:]
            return run_ingest()
        if mode == "--query":
            sys.argv = ["query.py", "--q"] + sys.argv[2:]
            return run_query()
        if mode == "--socket":
            sys.argv = ["socket.py"]
            return run_socket()
    print(
        "Usage:\n  python -m src.main --ingest <path1> <path2>\n"
        "python -m src.main --query 'your question'\n"
        "python -m src.main --socket"
    )


if __name__ == "__main__":
    main()
