from unittest.mock import MagicMock
from pytest_readable import readable

from src.workflows.query.engine import RAGEngine, _build_user_filter
from src.workflows.query.interfaces.vector_interface import ScoredItem


def _build_engine():
    embedding = MagicMock()
    embedding.generate.return_value = [0.2, 0.4]

    vector = MagicMock()
    vector.search.return_value = [ScoredItem(id="doc1", score=0.91, payload={"content": "vector context"})]
    vector.iter_payloads.return_value = iter(())

    graph = MagicMock()
    graph.search.return_value = ["nodeA -[REL]-> nodeB"]

    cache = MagicMock()
    cache.get.return_value = None

    llm = MagicMock()
    llm.complete.return_value = "Answer from LLM"

    return RAGEngine(
        embedding=embedding,
        vector_store=vector,
        graph_store=graph,
        cache=cache,
        llm=llm,
        mark_cache=True,
        default_top_k=7,
        default_tenant="tenant-default",
    )


@readable(
    intent="Verify the engine applies access filters and search parameters correctly.",
    steps=[
        "Create a RAGEngine with test doubles",
        "Run a query with explicit user_id and tenant_id",
        "Inspect the call sent to the vector store",
    ],
    criteria=[
        "The query uses the expected tenant_id and top_k",
        "Filters include owner_id, user_id, and visibility=public",
    ],
)
def test_rag_engine_applies_access_filters_and_search_params():
    engine = _build_engine()

    response = engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")

    assert response == "Answer from LLM"
    _, call_kwargs = engine.vector.search.call_args
    assert call_kwargs["tenant_id"] == "tenant-A"
    assert call_kwargs["top_k"] == 7
    assert call_kwargs["filters"] == {
        "user_id": "user-42",
        "owner_id": "user-42",
        "visibility": "public",
    }


@readable(
    intent="Validate that the prompt combines vector and graph context before calling the LLM.",
    steps=[
        "Create a RAGEngine with spy stores",
        "Run a query",
        "Inspect the prompt built for the LLM",
    ],
    criteria=[
        "The prompt includes content retrieved from the vector store",
        "The prompt includes graph store results",
    ],
)
def test_rag_engine_builds_prompt_with_vector_and_graph_context():
    engine = _build_engine()

    engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")

    prompt = engine.llm.complete.call_args[0][0]
    assert "vector context" in prompt
    assert "nodeA -[REL]-> nodeB" in prompt


@readable(
    intent="Confirm that a repeated identical query uses cache and avoids duplicate searches.",
    steps=[
        "Create a RAGEngine with cache enabled",
        "Run the same question twice",
        "Compare the number of vector store calls",
    ],
    criteria=[
        "The second response is marked as cached",
        "Only one vector search is executed",
    ],
)
def test_rag_engine_reuses_cached_answer_for_identical_query():
    engine = _build_engine()

    # Simulate real cache behaviour: get returns None on first call, stored value on second
    _store: dict = {}

    def _cache_get(key):
        return _store.get(key)

    def _cache_set(key, value):
        _store[key] = value

    engine.cache.get.side_effect = _cache_get
    engine.cache.set.side_effect = _cache_set

    engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")
    cached = engine.answer("What is Graphiti?", user_id="user-42", tenant_id="tenant-A")

    assert cached.startswith("[CACHE] Answer from LLM")
    assert engine.vector.search.call_count == 1


@readable(
    intent="Check user filters for anonymous and authenticated scenarios.",
    steps=[
        "Build filter for an anonymous user",
        "Build filter for an authenticated user",
    ],
    criteria=[
        "Anonymous users only see public content",
        "Authenticated users get owner_id and user_id plus visibility=public",
    ],
)
def test_build_user_filter_handles_anonymous_and_authenticated():
    anonymous = _build_user_filter(None)
    assert anonymous == {"visibility": "public"}

    auth = _build_user_filter("user-99")
    assert auth["owner_id"] == "user-99"
    assert auth["user_id"] == "user-99"
    assert auth["visibility"] == "public"