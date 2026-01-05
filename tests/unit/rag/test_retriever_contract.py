"""Tests for retriever contract compatibility."""
import pytest
from unittest.mock import Mock, MagicMock
from src.rag.retrieval.weaviate_retriever import WeaviateRetriever


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


class TestEmbeddingWeaviateRetriever:
    """Test CLI's EmbeddingWeaviateRetriever returns correct contract."""

    def test_cli_retriever_returns_tuple(self):
        """Test that EmbeddingWeaviateRetriever.retrieve returns tuple."""
        from src.query.cli import EmbeddingWeaviateRetriever

        # Mock dependencies
        mock_weaviate_retriever = Mock()
        mock_embedding_service = Mock()

        # Mock collection query
        mock_collection = Mock()
        mock_response = Mock()
        mock_response.objects = []

        mock_collection.query.near_vector.return_value = mock_response
        mock_weaviate_retriever.collection = mock_collection
        mock_weaviate_retriever.top_k = 5
        mock_weaviate_retriever._build_filters.return_value = None

        # Mock embedding generation
        mock_embedding_service.generate.return_value = [0.1] * 768

        # Create wrapper retriever
        retriever = EmbeddingWeaviateRetriever(
            weaviate_retriever=mock_weaviate_retriever,
            embedding_service=mock_embedding_service,
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
        assert "embedding_time_ms" in metadata, "metadata must contain embed time"
        assert "search_time_ms" in metadata, "metadata must contain search time"
        assert "total_time_ms" in metadata, "metadata must contain total time"

    def test_cli_retriever_handles_errors(self):
        """Test that EmbeddingWeaviateRetriever handles errors gracefully."""
        from src.query.cli import EmbeddingWeaviateRetriever

        # Mock dependencies
        mock_weaviate_retriever = Mock()
        mock_embedding_service = Mock()

        # Mock collection query to raise error
        mock_collection = Mock()
        mock_collection.query.near_vector.side_effect = Exception("Connection error")

        mock_weaviate_retriever.collection = mock_collection
        mock_weaviate_retriever.top_k = 5
        mock_weaviate_retriever._build_filters.return_value = None

        # Mock embedding generation
        mock_embedding_service.generate.return_value = [0.1] * 768

        # Create wrapper retriever
        retriever = EmbeddingWeaviateRetriever(
            weaviate_retriever=mock_weaviate_retriever,
            embedding_service=mock_embedding_service,
        )

        # Execute retrieval
        result = retriever.retrieve("test query")

        # Assert it returns a tuple even on error
        assert isinstance(result, tuple), "retrieve() must return tuple on error"
        assert len(result) == 2, "retrieve() must return (results, metadata) on error"

        results, metadata = result

        # Assert results is None on error
        assert results is None, "results must be None on error"

        # Assert metadata contains error info
        assert metadata.get("error") is not None, "metadata must contain error"
        assert metadata.get("error_type") is not None, "metadata must contain type"
