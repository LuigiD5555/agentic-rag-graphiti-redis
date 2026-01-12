"""Agent facade used by CLI entrypoints."""


class Agent:
    """Agent class that interacts with the RAG engine to answer questions."""

    def __init__(self, rag_engine):
        self.rag_engine = rag_engine

    def run(self, query):
        """Run the agent with the given query."""
        return self.rag_engine.answer(query)
