"""Pytest diagnostics for ChatMemory collection initialization."""

import pytest
import weaviate

from src.workflows.memory.storage.chat_memory_schema import (
    CHAT_MEMORY_COLLECTION,
    create_chat_memory_collection,
    get_chat_memory_collection,
)
from src.workflows.memory.storage.chat_memory_persistence import ChatMemoryPersistence
from pytest_readable import readable



pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_weaviate,
]


@readable(
    intent="Verify chatmemory initialization.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the chatmemory initialization behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_chatmemory_initialization():
    client = weaviate.connect_to_local(
        host="localhost",
        port=8080,
        grpc_port=50051,
    )
    try:
        exists = client.collections.exists(CHAT_MEMORY_COLLECTION)
        assert isinstance(exists, bool)

        created = create_chat_memory_collection(client, force_recreate=False)
        assert created is True

        collection = get_chat_memory_collection(client, auto_create=True)
        assert collection is not None
        assert collection.name == CHAT_MEMORY_COLLECTION

        persistence = ChatMemoryPersistence(client, embedding_service=None)
        assert persistence.collection is not None
    finally:
        client.close()
