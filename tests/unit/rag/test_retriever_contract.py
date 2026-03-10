"""Tests for retriever contract compatibility."""

from unittest.mock import MagicMock
from pytest_readable import readable

from src.workflows.query.retrieval.weaviate_retriever import WeaviateRetriever


def _make_client(*, response=None, exception=None):
    """Build a minimal Weaviate client mock."""
    if exception:
        hybrid = MagicMock(side_effect=exception)
    else:
        hybrid = MagicMock(return_value=response or MagicMock(objects=[]))

    collection = MagicMock()
    collection.with_tenant.return_value = collection
    collection.query.hybrid = hybrid

    client = MagicMock()
    client.collections.get.return_value = collection
    return client


@readable(
    intent="Verify that retrieve always keeps the (results, metadata) contract.",
    steps=[
        "Prepare a Weaviate client stub that returns an empty result set",
        "Run retrieve with a basic query",
        "Assert metadata contains minimum fields",
    ],
    criteria=[
        "Return value is a tuple of length 2",
        "Results is a list or None",
        "Metadata holds query, top_k, and total_time_ms",
    ],
)
class TestRetrieverContract:
    """Test that retrievers return (results, metadata) tuple."""

    @readable(
        intent="Verify weaviate retriever returns tuple in retriever contract.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the weaviate retriever returns tuple behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_weaviate_retriever_returns_tuple(self):
        client = _make_client()
        retriever = WeaviateRetriever(client=client, collection_name="TestCollection", top_k=5)
        result = retriever.retrieve("test query")

        assert isinstance(result, tuple)
        assert len(result) == 2

        results, metadata = result
        assert results is None or isinstance(results, list)
        assert isinstance(metadata, dict)
        assert "query" in metadata
        assert "top_k" in metadata
        assert "total_time_ms" in metadata


@readable(
    intent="Ensure backend errors do not break the retriever output contract.",
    steps=[
        "Configure the hybrid query to raise an exception",
        "Run retrieve",
        "Inspect error metadata",
    ],
    criteria=[
        "A tuple of length 2 is always returned",
        "Results is None",
        "Metadata includes error and error_type",
    ],
)
def test_retriever_handles_errors_and_preserves_tuple_contract():
    client = _make_client(exception=Exception("Connection error"))
    retriever = WeaviateRetriever(client=client, collection_name="TestCollection", top_k=5)
    results, metadata = retriever.retrieve("test query")

    assert isinstance((results, metadata), tuple)
    assert len((results, metadata)) == 2
    assert results is None
    assert metadata.get("error")
    assert metadata.get("error_type")
