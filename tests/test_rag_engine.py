from src.rag.engine import RAGEngine, _build_user_filter
from src.interfaces.vector_interface import ScoredItem


class DummyEmbedding:
    def __init__(self):
        self.calls = []

    def generate(self, text):
        self.calls.append(text)
        return [0.2, 0.4]


class SpyVectorStore:
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
        return [
            ScoredItem(
                id="doc1",
                score=0.91,
                payload={"content": "vector context"},
            )
        ]

    def iter_payloads(self, batch_size=256, tenant_id=None):
        return iter(())


class SpyGraphStore:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return ["nodeA -[REL]-> nodeB"]


class SpyCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


class SpyLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "Answer from LLM"


def test_rag_engine_respects_access_controls_and_cache():
    engine = RAGEngine(
        embedding=DummyEmbedding(),
        vector_store=SpyVectorStore(),
        graph_store=SpyGraphStore(),
        cache=SpyCache(),
        llm=SpyLLM(),
        mark_cache=True,
        default_top_k=7,
        default_tenant="tenant-default",
    )

    response = engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")
    assert response == "Answer from LLM"

    vector_call = engine.vector.calls[0]
    assert vector_call["tenant_id"] == "tenant-A"
    assert vector_call["top_k"] == 7
    assert vector_call["filters"] == {
        "user_id": "user-42",
        "owner_id": "user-42",
        "visibility": "public",
    }

    prompt = engine.llm.prompts[0]
    assert "vector context" in prompt
    assert "nodeA -[REL]-> nodeB" in prompt

    # Second call should come from cache and avoid extra search.
    cached = engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")
    assert cached.startswith("[CACHE] Answer from LLM")
    assert len(engine.vector.calls) == 1


def test_build_user_filter_handles_anonymous_and_authenticated():
    anonymous = _build_user_filter(None)
    assert anonymous == {"visibility": "public"}

    auth = _build_user_filter("user-99")
    assert auth["owner_id"] == "user-99"
    assert auth["user_id"] == "user-99"
    assert auth["visibility"] == "public"
