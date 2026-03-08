"""Tests for retriever contract compatibility."""
from unittest.mock import Mock
from src.workflows.query.retrieval.weaviate_retriever import WeaviateRetriever


class TestRetrieverContract:
    """Test that retrievers return (results, metadata) tuple."""

    def test_weaviate_retriever_returns_tuple(self):
        """Test that WeaviateRetriever.retrieve returns (results, metadata)."""
        # Mock Weaviate client and collection
        mock_client = Mock()
        mock_collection = Mock()
        mock_response = Mock()
        mock_response.objects = []

        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection

        # Create retriever
        retriever = WeaviateRetriever(
            client=mock_client,
            collection_name="TestCollection",
            top_k=5
        )

        # Execute retrieval
        result = retriever.retrieve("test query")

        # Assert it returns a tuple
        assert isinstance(result, tuple), "retrieve() must return tuple"
        assert len(result) == 2, "retrieve() must return (results, metadata)"

        results, metadata = result

        # Assert results is a list (or None on error)
        assert results is None or isinstance(
            results, list
        ), "results must be list or None"

        # Assert metadata is a dict
        assert isinstance(metadata, dict), "metadata must be dict"
        assert "query" in metadata, "metadata must contain 'query'"
        assert "top_k" in metadata, "metadata must contain 'top_k'"
        assert "total_time_ms" in metadata, "metadata must contain timing info"


def test_retriever_handles_errors_and_preserves_tuple_contract():
    """Retriever should return (None, metadata) when query backend errors."""
    mock_client = Mock()
    mock_collection = Mock()
    mock_collection.query.hybrid.side_effect = Exception("Connection error")
    mock_client.collections.get.return_value = mock_collection

    retriever = WeaviateRetriever(client=mock_client, collection_name="TestCollection", top_k=5)
    result = retriever.retrieve("test query")

    assert isinstance(result, tuple)
    assert len(result) == 2
    results, metadata = result
    assert results is None
    assert metadata.get("error") is not None
    assert metadata.get("error_type") is not None
