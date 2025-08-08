from src.vectorstore import VectorStoreService
from src.config import Config


def test_vectorstore_upsert(monkeypatch):
    config = Config()
    service = VectorStoreService(config)

    upsert_called = {"called": False}

    # Patch methods of the real client
    monkeypatch.setattr(service.client, "collection_exists", lambda name: True)
    monkeypatch.setattr(service.client, "search", lambda **kwargs: [{"payload": {"content": "test"}}])
    monkeypatch.setattr(service.client, "upsert", lambda **kwargs: upsert_called.update(called=True))

    service.upsert("key", [0.1, 0.2], {"content": "text"})
    assert upsert_called["called"]
