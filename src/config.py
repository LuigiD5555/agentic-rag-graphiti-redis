import os
from dotenv import load_dotenv


class Config:
    def __init__(self):
        load_dotenv()

        # Qdrant
        self.QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "rag_docs")

        self.EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

        # Redis
        self.REDIS_HOST = os.getenv("REDIS_HOST", "redis")
        self.REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

        # Neo4j
        self.NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        self.NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
        self.NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

        # LM Studio host & port
        self.LMSTUDIO_HOST = os.getenv("LMSTUDIO_HOST", "host.containers.internal")
        self.LMSTUDIO_PORT = int(os.getenv("LMSTUDIO_PORT", "1234"))

        # Document ingestion
        self.DOCS_PATH = os.getenv("DOCS_PATH", "/mnt/Documents/Documents")
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

        # Cache TTL
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

    @property
    def LM_EMBED_URL(self):
        return f"http://{self.LMSTUDIO_HOST}:{self.LMSTUDIO_PORT}/v1/embeddings"

    @property
    def LM_LLM_URL(self):
        return f"http://{self.LMSTUDIO_HOST}:{self.LMSTUDIO_PORT}/v1/completions"
