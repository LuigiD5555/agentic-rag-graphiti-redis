from src.rag.cli.agent import Agent
from src.rag.engine import RAGEngine
from src.rag.interfaces.vector_interface import ScoredItem


class DummyEmbedding:
    def generate(self, text):
        return [0.1, 0.2]


class DummyVector:
    def __init__(self):
        self.calls = []

    def search(self, vector, top_k=5, filters=None, tenant_id=None):
        self.calls.append(
            {
                "vector": list(vector),
                "top_k": top_k,
                "filters": dict(filters or {}),
                "tenant_id": tenant_id,
            }
        )
        return [ScoredItem(id="1", score=0.9, payload={"content": "context snippet"})]

    def iter_payloads(self, batch_size=256, tenant_id=None):
        return iter(())


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
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "Final Answer"


def test_end_to_end_flow_uses_context_and_cache():
    embedding = DummyEmbedding()
    vector = DummyVector()
    graph = DummyGraph()
    cache = DummyCache()
    llm = DummyLLM()

    rag = RAGEngine(
        embedding=embedding,
        vector_store=vector,
        graph_store=graph,
        cache=cache,
        llm=llm,
        mark_cache=True,
        default_top_k=3,
        default_tenant="tenant-default",
    )
    agent = Agent(rag)

    first = agent.run("Question?",)
    assert "Final Answer" in first
    assert vector.calls[0]["filters"]["visibility"] == "public"

    second = agent.run("Question?")
    assert second.startswith("[CACHE]")
