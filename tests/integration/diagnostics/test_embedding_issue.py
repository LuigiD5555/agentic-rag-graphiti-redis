"""Pytest diagnostics for embedding + Weaviate integration."""

import uuid

import pytest
import weaviate

from src.backends.llm.factory import ProviderFactory
from src.conf import settings
from src.workflows.query.embeddings_factory import get_embedding_service
from pytest_readable import readable



pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_weaviate,
    pytest.mark.requires_lmstudio,
]


def _connect_client():
    return weaviate.connect_to_local(
        host="localhost",
        port=8080,
        grpc_port=50051,
    )


@readable(
    intent="Verify embedding generation.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embedding generation behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embedding_generation():
    provider = ProviderFactory.get_provider("lmstudio")
    embedding_service = get_embedding_service(settings, provider)
    embedding = embedding_service.generate("Este es un texto de prueba para embeddings")

    assert len(embedding) == settings.EMBEDDING_DIM
    assert not all(abs(value) < 0.0001 for value in embedding)


@readable(
    intent="Verify weaviate connection.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the weaviate connection behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_weaviate_connection():
    client = _connect_client()
    try:
        collection = client.collections.get(settings.WEAVIATE_CLASS)
        assert collection is not None

        if settings.WEAVIATE_MULTI_TENANCY:
            tenants = collection.tenants.get()
            assert tenants is not None
    finally:
        client.close()


@readable(
    intent="Verify vector storage roundtrip.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the vector storage roundtrip behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_vector_storage_roundtrip():
    client = _connect_client()
    try:
        collection = client.collections.get(settings.WEAVIATE_CLASS)

        provider = ProviderFactory.get_provider("lmstudio")
        embedding_service = get_embedding_service(settings, provider)
        test_text = "Texto de prueba para almacenamiento vectorial"
        embedding = embedding_service.generate(test_text)

        test_id = str(uuid.uuid4())
        properties = {
            "content": test_text,
            "source": "pytest",
            "file_name": "test.txt",
            "visibility": "private",
            "owner_id": "test_user",
            "allowed_user_ids": ["test_user"],
            "hash": test_id,
            "chunk_index": 0,
            "chunk_total": 1,
            "archived": False,
        }

        tenant = settings.WEAVIATE_DEFAULT_TENANT if settings.WEAVIATE_MULTI_TENANCY else None
        coll_with_tenant = collection.with_tenant(tenant) if tenant else collection

        coll_with_tenant.data.insert(uuid=test_id, properties=properties, vector=embedding)
        obj = coll_with_tenant.query.fetch_object_by_id(test_id, include_vector=True)

        try:
            assert obj is not None
            assert obj.vector is not None
            assert len(obj.vector) == settings.EMBEDDING_DIM
        finally:
            coll_with_tenant.data.delete_by_id(test_id)
    finally:
        client.close()


@readable(
    intent="Verify existing vectors.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the existing vectors behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_existing_vectors():
    client = _connect_client()
    try:
        collection = client.collections.get(settings.WEAVIATE_CLASS)
        tenant = settings.WEAVIATE_DEFAULT_TENANT if settings.WEAVIATE_MULTI_TENANCY else None
        coll_with_tenant = collection.with_tenant(tenant) if tenant else collection

        response = coll_with_tenant.query.fetch_objects(limit=5, include_vector=True)
        objects = response.objects
        if not objects:
            pytest.skip("No vectors stored yet in Weaviate.")

        assert any(obj.vector is not None for obj in objects)
    finally:
        client.close()
