"""
Interface subpackage.

Do not eagerly import all interfaces here: importing this package should not
trigger optional heavy dependencies (e.g. LangChain loaders).

Import interfaces from their concrete modules instead, e.g.:
    from src.rag.interfaces.vector_interface import VectorInterface
"""

__all__: list[str] = []
