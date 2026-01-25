"""Helper to instantiate and tear down the RAG runtime for FastAPI."""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Mapping

import weaviate

from src.apps.websearch import SearXNGClient
from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.backends.llm.factory import ProviderFactory
from src.workflows.query.embeddings_factory import get_embedding_service
from src.workflows.query.pipeline.rag_orchestrator import RAGOrchestrator
from src.workflows.query.retrieval import WeaviateRetriever

log = logging.getLogger(__name__)


@dataclass
class RuntimeResources:
    config: Any
    weaviate_client: Any
    retriever: WeaviateRetriever
    rag_orchestrator: RAGOrchestrator
    ingestion_orchestrator: IngestionOrchestrator
    embedding_service: Any
    chat_memory_manager: Optional[Any]
    snapshot_scheduler: Optional[Any]
    cleanup_scheduler: Optional[Any]
    temporal_cleanup_scheduler: Optional[Any]
    web_search_client: Optional[SearXNGClient]


class RuntimeContext:
    """Context manager for runtime resources."""

    def __init__(self, factory: "RuntimeFactory") -> None:
        self._factory = factory
        self.resources: Optional[RuntimeResources] = None

    def __enter__(self) -> RuntimeResources:
        self.resources = self._factory.create()
        return self.resources

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._factory.shutdown(self.resources)
        self.resources = None


class RuntimeFactory:
    """Builds and tears down the FastAPI runtime stack."""

    def __init__(self, config: Any, rag_overrides: Mapping[str, Any] | None = None) -> None:
        self.config = config
        self._rag_overrides = dict(rag_overrides or {})

    def context(self) -> "RuntimeContext":
        return RuntimeContext(self)

    def create(self) -> RuntimeResources:
        cfg = self.config
        log.info("Initializing RAG runtime...")

        weaviate_client = weaviate.connect_to_local(
            host=cfg.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
            port=int(cfg.WEAVIATE_URL.split(":")[-1]) if ":" in cfg.WEAVIATE_URL else 8080,
            grpc_port=cfg.WEAVIATE_GRPC_PORT,
        )

        from src.backends.storage.vector import get_vector_store

        log.info("Ensuring Weaviate schema exists...")
        get_vector_store(cfg)
        log.info("Weaviate schema ready")

        from src.workflows.memory.storage.chat_memory_schema import create_chat_memory_collection

        log.info("Ensuring ChatMemory collection exists...")
        chat_memory_created = create_chat_memory_collection(
            weaviate_client,
            config=cfg,
            force_recreate=False,
        )
        if chat_memory_created:
            log.info("ChatMemory collection ready")
        else:
            log.warning("ChatMemory collection creation failed - memory features may not work")

        provider = ProviderFactory(cfg)
        embedding_service = get_embedding_service(cfg, provider)
        retriever = WeaviateRetriever(
            client=weaviate_client,
            collection_name=cfg.WEAVIATE_CLASS,
            tenant=cfg.WEAVIATE_DEFAULT_TENANT if cfg.WEAVIATE_MULTI_TENANCY else None,
            top_k=None,
            embedding_service=embedding_service,
        )

        chat_service = provider.chat()
        rag_kwargs = dict(self._rag_overrides)
        rag_orchestrator = RAGOrchestrator(
            retriever=retriever,
            chat_service=chat_service,
            **rag_kwargs,
        )
        log.info("RAG orchestrator initialized")

        ingestion_orchestrator = IngestionOrchestrator(cfg)
        log.info("Ingestion orchestrator initialized")

        chat_memory_manager: Optional[Any] = None
        try:
            from src.workflows.memory import ChatMemoryManager

            chat_memory_manager = ChatMemoryManager(
                weaviate_client=weaviate_client,
                embedding_service=embedding_service,
                snapshot_ttl_days=cfg.SNAPSHOT_TTL_DAYS,
            )
            log.info("Chat memory manager initialized")
        except Exception as exc:  # pragma: no cover - best-effort
            log.error("Failed to initialize chat memory manager: %s", exc)

        snapshot_scheduler = None
        if cfg.SNAPSHOT_ENABLED:
            try:
                from src.workflows.memory.snapshot_scheduler import SnapshotScheduler

                snapshot_scheduler = SnapshotScheduler(
                    snapshot_interval=cfg.SNAPSHOT_INTERVAL_HOURS * 3600,
                )
                log.info("Snapshot scheduler initialized")
            except Exception as exc:  # pragma: no cover - optional
                log.error("Failed to initialize snapshot scheduler: %s", exc)

        cleanup_scheduler = None
        if cfg.CLEANUP_ENABLED:
            try:
                from src.workflows.memory.cleanup_scheduler import CleanupScheduler

                cleanup_scheduler = CleanupScheduler(
                    chat_memory_manager=chat_memory_manager,
                    snapshot_scheduler=snapshot_scheduler,
                    cleanup_interval=cfg.CLEANUP_INTERVAL_HOURS * 3600,
                )
                log.info("Cleanup scheduler initialized")
            except Exception as exc:  # pragma: no cover - optional
                log.error("Failed to initialize cleanup scheduler: %s", exc)

        temporal_scheduler = None
        if cfg.TEMPORAL_CLEANUP_ENABLED:
            try:
                from src.workflows.query.temporal.cleanup_scheduler import create_temporal_cleanup_scheduler
                from src.workflows.query.temporal.tenant_manager import create_temporal_tenant_manager
                from src.workflows.query.temporal.store import TemporalStore

                store = TemporalStore()
                tenant_manager = create_temporal_tenant_manager(
                    weaviate_client=weaviate_client,
                    collection_name=cfg.WEAVIATE_CLASS,
                    ttl_seconds=cfg.TEMPORAL_TENANT_TTL,
                    store=store,
                )
                temporal_scheduler = create_temporal_cleanup_scheduler(
                    tenant_manager=tenant_manager,
                    cleanup_interval=cfg.TEMPORAL_CLEANUP_INTERVAL_HOURS * 3600,
                )
                temporal_scheduler.start()
                log.info("Temporal cleanup scheduler started")
            except Exception as exc:  # pragma: no cover - optional
                log.error("Failed to initialize temporal cleanup scheduler: %s", exc)

        web_search_client = None
        if getattr(cfg, "WEB_SEARCH_ENABLED", False):
            try:
                web_search_client = SearXNGClient(
                    base_url=getattr(cfg, "SEARXNG_URL", "http://localhost:8080"),
                    timeout=getattr(cfg, "SEARXNG_TIMEOUT", 10),
                )
                log.info("Web search client initialized")
            except Exception as exc:  # pragma: no cover - optional
                log.error("Failed to initialize web search client: %s", exc)
                web_search_client = None

        log.info("RAG runtime initialization complete")
        return RuntimeResources(
            config=cfg,
            weaviate_client=weaviate_client,
            retriever=retriever,
            rag_orchestrator=rag_orchestrator,
            ingestion_orchestrator=ingestion_orchestrator,
            embedding_service=embedding_service,
            chat_memory_manager=chat_memory_manager,
            snapshot_scheduler=snapshot_scheduler,
            cleanup_scheduler=cleanup_scheduler,
            temporal_cleanup_scheduler=temporal_scheduler,
            web_search_client=web_search_client,
        )

    def shutdown(self, resources: Optional[RuntimeResources]) -> None:
        """Stop schedulers and close clients."""
        if not resources:
            return

        for scheduler, name in [
            (resources.snapshot_scheduler, "snapshot"),
            (resources.cleanup_scheduler, "cleanup"),
            (resources.temporal_cleanup_scheduler, "temporal cleanup"),
        ]:
            if scheduler:
                try:
                    scheduler.stop()
                    log.info("%s scheduler stopped", name)
                except Exception as exc:  # pragma: no cover - optional
                    log.error("Error stopping %s scheduler: %s", name, exc)

        if resources.weaviate_client:
            try:
                resources.weaviate_client.close()
                log.info("Weaviate client closed")
            except Exception as exc:  # pragma: no cover - optional
                log.error("Error closing Weaviate client: %s", exc)
