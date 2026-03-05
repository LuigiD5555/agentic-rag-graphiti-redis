"""Ingestion worker that consumes jobs from RabbitMQ and executes them."""

import asyncio
import os
import socket
import time
from typing import Dict, Any, Optional

from src.workflows.ingestion.jobs.models import IngestionJobMessage, IngestionPhase
from src.workflows.ingestion.state.job_state_repository import JobStateRepository
from src.workflows.ingestion.rabbitmq_queue import RabbitMQIngestQueue
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


def _build_pipeline():
    """Build an IngestionPipeline with services from runtime config.

    Mirrors the logic in IngestionOrchestrator._build_pipeline().
    Called lazily the first time the worker processes a job.
    """
    from src.conf import settings as runtime_settings
    from src.workflows.ingestion.options import PipelineOptions
    from src.workflows.ingestion.pipeline import IngestionPipeline
    from src.backends.storage.cache.ingestion.manager import IngestionCacheManager
    from src.backends.storage.vector import get_vector_store
    from src.workflows.query.embeddings_factory import get_embedding_service
    from src.backends.llm.factory import ProviderFactory
    from src.ingestion.ledger.ledger_repository import LedgerRepository

    cfg = runtime_settings
    provider = ProviderFactory(cfg)
    embedding_service = get_embedding_service(cfg, provider)
    vector_store = get_vector_store(cfg)

    pipeline_options = PipelineOptions(
        chunk_size=getattr(cfg, "CHUNK_SIZE", 800),
        chunk_overlap=getattr(cfg, "CHUNK_OVERLAP", 50),
        embedding_token_limit=getattr(cfg, "EMBEDDING_MAX_TOKENS", 0) or 0,
        tenant_id=(
            getattr(cfg, "WEAVIATE_DEFAULT_TENANT", None)
            if getattr(cfg, "WEAVIATE_MULTI_TENANCY", False)
            else None
        ),
        owner_id=getattr(cfg, "INGESTION_OWNER_ID", None),
        visibility=getattr(cfg, "INGESTION_VISIBILITY", "private"),
        allowed_user_ids=list(getattr(cfg, "INGESTION_ALLOWED_USER_IDS", ()) or ()),
        splitter_strategy=getattr(cfg, "INGESTION_SPLITTER_STRATEGY", None),
        tokenizer_model_name=getattr(cfg, "INGESTION_TOKENIZER_MODEL", "gpt-4o-mini"),
        markdown_levels=getattr(cfg, "INGESTION_MARKDOWN_LEVELS", None),
        semantic_embeddings=getattr(cfg, "INGESTION_SEMANTIC_EMBEDDINGS", None),
        include_duplicates_patterns=tuple(getattr(cfg, "INGEST_DUPLICATE_PATTERNS", ()) or ()),
    )

    settings_dict = {}
    if hasattr(cfg, "model_dump"):
        settings_dict = cfg.model_dump()
    elif hasattr(cfg, "__dict__"):
        settings_dict = {k: v for k, v in cfg.__dict__.items() if not k.startswith("_")}

    cache_manager = IngestionCacheManager.from_settings(settings_dict)

    pipeline = IngestionPipeline.from_options(
        embedding_service=embedding_service,
        vector_store=vector_store,
        options=pipeline_options,
        cache_manager=cache_manager,
    )
    pipeline.ledger = LedgerRepository()
    pipeline.disable_preprocessing = False
    return pipeline


class IngestionWorker:
    """Worker that consumes jobs from RabbitMQ and executes them.

    Follows specification: Worker consumes, checks SQLite, executes, updates SQLite, ACKs.
    """

    def __init__(
        self,
        worker_name: Optional[str] = None,
        state_repository: Optional[JobStateRepository] = None,
        max_retries: int = 3,
    ):
        self.worker_name = worker_name or self._generate_worker_name()
        self.state_repository = state_repository or JobStateRepository()
        self.queue = None
        self.max_retries = max_retries
        self.running = False
        self._pipeline = None

        log.info("IngestionWorker initialized: %s", self.worker_name)

    def _generate_worker_name(self) -> str:
        hostname = socket.gethostname()
        pid = os.getpid()
        return f"{hostname}_{pid}"

    def _get_pipeline(self):
        """Return the shared pipeline instance, building it on first call."""
        if self._pipeline is None:
            log.info("Worker %s: building ingestion pipeline", self.worker_name)
            self._pipeline = _build_pipeline()
        return self._pipeline

    async def connect_queue(self) -> None:
        if not self.queue:
            self.queue = RabbitMQIngestQueue(max_retries=self.max_retries)
            await self.queue.connect()

    async def process_job(self, job: IngestionJobMessage) -> Dict[str, Any]:
        """Process a single job (idempotence gate → execute → update SQLite)."""
        log.debug(
            "Worker %s processing job %s (phase=%s, file=%s)",
            self.worker_name, job.job_id, job.phase.value, job.file_path,
        )

        decision = self.state_repository.try_claim(job)

        if decision.skip:
            log.debug("Skipping job %s: %s", job.job_id, decision.reason)
            return {"success": True, "skipped": True, "reason": decision.reason, "job_id": job.job_id}

        if decision.retry:
            log.info("Retrying job %s: %s", job.job_id, decision.reason)

        try:
            result = await self._execute_phase(job)

            if result.get("success", False):
                self.state_repository.mark_done(job, result.get("metrics", {}))
                log.debug("Job %s completed successfully", job.job_id)
                return {"success": True, "job_id": job.job_id, "metrics": result.get("metrics", {})}
            else:
                error = result.get("error", "Unknown error")
                retryable = result.get("retryable", True)
                self.state_repository.mark_failed(job, error, retryable)
                log.warning("Job %s failed: %s", job.job_id, error)
                return {"success": False, "job_id": job.job_id, "error": error, "retryable": retryable}

        except Exception as e:
            error_msg = f"Unexpected error processing job {job.job_id}: {e}"
            log.error(error_msg, exc_info=True)
            self.state_repository.mark_failed(job, error_msg, retryable=True)
            return {"success": False, "job_id": job.job_id, "error": error_msg, "retryable": True}

    async def _execute_phase(self, job: IngestionJobMessage) -> Dict[str, Any]:
        """Execute real work for a job phase via the ingestion pipeline.

        The existing pipeline processes a file end-to-end (extract → chunk → embed → upsert)
        in a single synchronous call, so only the EXTRACT phase triggers real work.
        Subsequent phases (CHUNK, EMBED, UPSERT) for the same file are no-ops here because
        the work was already done; idempotence is enforced by the JobStateRepository.
        FINALIZE updates the ledger to mark the file as fully ingested.
        """
        log.info("Executing phase %s for file %s", job.phase.value, job.file_path)
        t0 = time.monotonic()

        if job.phase == IngestionPhase.EXTRACT:
            return await self._run_full_pipeline(job, t0)

        if job.phase in (IngestionPhase.CHUNK, IngestionPhase.EMBED, IngestionPhase.UPSERT):
            # Work already done inside EXTRACT; mark as pass-through.
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "success": True,
                "metrics": {"phase": job.phase.value, "file": job.file_path, "duration_ms": elapsed_ms},
            }

        if job.phase == IngestionPhase.FINALIZE:
            return self._finalize(job, t0)

        return {
            "success": False,
            "error": f"Unknown phase: {job.phase.value}",
            "retryable": False,
        }

    async def _run_full_pipeline(self, job: IngestionJobMessage, t0: float) -> Dict[str, Any]:
        """Run the full ingestion pipeline for a single file (blocking, in thread pool)."""
        from src.workflows.ingestion.pipeline.file_processor import process_candidate_file

        pipeline = self._get_pipeline()
        pipeline.start_ingestion_run()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: process_candidate_file(pipeline, job.file_path),
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return {
                "success": False,
                "error": str(exc),
                "retryable": True,
                "metrics": {"phase": job.phase.value, "file": job.file_path, "duration_ms": elapsed_ms},
            }

        pipeline.finish_ingestion_run()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "success": True,
            "metrics": {
                "phase": job.phase.value,
                "file": job.file_path,
                "duration_ms": elapsed_ms,
            },
        }

    def _finalize(self, job: IngestionJobMessage, t0: float) -> Dict[str, Any]:
        """Mark the file as fully ingested in the ledger."""
        try:
            pipeline = self._get_pipeline()
            ledger = getattr(pipeline, "ledger", None)
            if ledger is not None:
                from src.ingestion.ledger.ledger_repository import Stage
                doc_id = ledger.get_or_create_document(job.file_path)
                active_version = ledger.get_active_version(doc_id)
                if active_version:
                    ledger.complete_stage(active_version, Stage.UPSERT)
        except Exception as exc:
            log.warning("Finalize ledger update failed for %s: %s", job.file_path, exc)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "success": True,
            "metrics": {"phase": job.phase.value, "file": job.file_path, "duration_ms": elapsed_ms},
        }

    async def _job_callback(self, job: IngestionJobMessage, gate_result: Dict[str, Any]) -> Dict[str, Any]:
        return await self.process_job(job)

    async def run(self, concurrency: int = 4, prefetch: int = 10) -> None:
        await self.connect_queue()

        self.running = True
        log.info(
            "Worker %s started with concurrency=%d, prefetch=%d",
            self.worker_name, concurrency, prefetch,
        )

        try:
            await self.queue.process_jobs(
                worker_name=self.worker_name,
                callback=self._job_callback,
                batch_size=concurrency,
            )
        except asyncio.CancelledError:
            log.info("Worker %s cancelled", self.worker_name)
            self.running = False
            raise
        except Exception as e:
            log.error("Worker %s stopped with error: %s", self.worker_name, e)
            self.running = False
            raise
        finally:
            self.running = False
            log.info("Worker %s stopped", self.worker_name)

    async def stop(self) -> None:
        self.running = False
        log.info("Worker %s stopping...", self.worker_name)

    def get_status(self) -> Dict[str, Any]:
        return {
            "worker_name": self.worker_name,
            "running": self.running,
            "max_retries": self.max_retries,
        }


async def start_worker_cluster(
    worker_count: int = 1,
    concurrency_per_worker: int = 4,
    max_retries: int = 3,
) -> None:
    """Start a cluster of ingestion workers."""
    workers = []

    log.info("Starting worker cluster with %d workers", worker_count)

    try:
        for i in range(worker_count):
            worker = IngestionWorker(
                worker_name=f"worker_{i + 1}",
                max_retries=max_retries,
            )
            workers.append(worker)

        tasks = [
            asyncio.create_task(worker.run(concurrency=concurrency_per_worker))
            for worker in workers
        ]

        await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        log.info("Keyboard interrupt received, stopping workers...")
    except Exception as e:
        log.error("Error in worker cluster: %s", e)
    finally:
        for worker in workers:
            try:
                await worker.stop()
            except Exception:
                pass
        log.info("Worker cluster stopped")
