import os
import tempfile
from src.document_loader import DocumentIngestor


class DummyEmbedding:
    def generate(self, text): return [0.1] * 768


class DummyVector:
    def upsert(self, key, vector, metadata): self.last_upsert = (key, metadata)


class DummyNER:
    def extract_and_insert(self, text): self.called = True


def test_ingest_creates_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        file_path = os.path.join(tmp, "test.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Sample text")

        ingestor = DocumentIngestor(DummyEmbedding(), DummyVector(), DummyNER())
        ingestor.ingest(tmp)
