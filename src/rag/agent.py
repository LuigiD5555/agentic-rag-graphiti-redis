"""This module defines the interface that allows to interact with the RAG engine."""


class Agent:
    """Agent class that interacts with the RAG engine to answer questions."""
    def __init__(self, rag_engine):
        self.rag_engine = rag_engine

    def run(self, query):
        """Run the agent with the given query.

        Args:
            query (str): The query to be answered by the RAG engine.

        Returns:
            str: The answer from the RAG engine.
        """
        return self.rag_engine.answer(query)
