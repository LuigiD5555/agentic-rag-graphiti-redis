from src.rag_chain import RAGEngine


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
        return "Answer"


def test_rag_answer_combines_context():
    rag = RAGEngine(DummyEmbedding(), DummyVector(), DummyGraph(), DummyCache(), DummyLLM())
    response = rag.answer("What is this?")
    assert "Answer" in response
