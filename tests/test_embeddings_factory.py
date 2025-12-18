import builtins

from src.rag.embeddings_factory import get_embedding_service


class ConfigStub:
    EMBEDDING_BACKEND = "local_gpu"


class ProviderStub:
    def __init__(self, value):
        self._value = value

    def embeddings(self):
        return self._value


def test_embeddings_factory_falls_back_when_torch_missing(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch":
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    sentinel = object()
    service = get_embedding_service(ConfigStub(), provider=ProviderStub(sentinel))

    assert service is sentinel

