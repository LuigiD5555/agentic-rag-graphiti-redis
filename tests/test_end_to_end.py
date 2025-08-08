from src.agent import Agent
from src.rag_chain import RAGEngine


# Dummy classes that fully implement the required protocols

class DummyEmbedding:
    def generate(self, text):
        return [0.1]


class DummyVector:
    def search(self, vector, top_k=5):
        return [{"payload": {"content": "context"}}]


class DummyGraph:
    def search(self, query):
        return ["Entity -[REL]-> Target"]


class DummyCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


class DummyLLM:
    def complete(self, prompt):
        return "Final Answer"


def test_end_to_end():
    # Instantiate dummy implementations
    embedding = DummyEmbedding()
    vector = DummyVector()
    graph = DummyGraph()
    cache = DummyCache()
    llm = DummyLLM()

    # Create RAG engine and agent
    rag = RAGEngine(embedding, vector, graph, cache, llm)
    agent = Agent(rag)

    # Validate final answer
    assert "Final Answer" in agent.run("Question?")
