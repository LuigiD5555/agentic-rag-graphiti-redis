"""
Resource Pools - Phase 4 of the optimization plan

Implements resource pools to limit heavy concurrent work,
prevent RAM/CPU saturation, and provide backpressure.
"""

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from queue import Queue, Empty
import time

from src import logger
from src.workflows.query.audit.decorators import logged, timed


@dataclass
class PoolMetrics:
    """Metrics for a resource pool."""
    active_tasks: int
    queued_tasks: int
    completed_tasks: int
    failed_tasks: int
    avg_task_time: float
    max_concurrent: int


class ResourcePool:
    """Generic concurrency-limited resource pool."""
    
    def __init__(
        self,
        name: str,
        max_workers: int,
        max_queue_size: int = 100
    ):
        """
        Args:
            name: Pool name for logging
            max_workers: Maximum number of concurrent tasks
            max_queue_size: Maximum queue size (backpressure)
        """
        self.name = name
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._queue = Queue(maxsize=max_queue_size)
        self._lock = threading.Lock()
        
        # Metrics
        self._active_tasks = 0
        self._queued_tasks = 0
        self._completed_tasks = 0
        self._failed_tasks = 0
        self._total_task_time = 0.0
        self._task_count = 0
        
        # State
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        
        logger.info(
            "ResourcePool '%s' initialized: max_workers=%d, max_queue=%d",
            name, max_workers, max_queue_size
        )
    
    def submit(self, task_fn: Callable, *args, **kwargs) -> Optional[Future]:
        """
        """Submits a task to the pool.
        
        Returns:
            Future if accepted, None if the queue is full (backpressure)
        """
        if not self._running:
            raise RuntimeError(f"Pool '{self.name}' has been shut down")
        
        # Check for backpressure
        if self._queue.qsize() >= self.max_queue_size:
            logger.warning(
                "Pool '%s': queue full (%d/%d), rejecting task (backpressure)",
                self.name, self._queue.qsize(), self.max_queue_size
            )
            return None
        
        # Create future and enqueue
        future = Future()
        task_data = {
            'fn': task_fn,
            'args': args,
            'kwargs': kwargs,
            'future': future,
            'submitted_at': time.time()
        }
        
        with self._lock:
            self._queued_tasks += 1
        
        self._queue.put(task_data)
        return future
    
    def submit_batch(self, tasks: List[tuple]) -> List[Optional[Future]]:
        """
        """Submits a batch of tasks to the pool.
        
        Args:
            tasks: List of tuples (task_fn, args, kwargs)
            
        Returns:
            List of Futures (may include None if a task was rejected)
        """
        futures = []
        for task in tasks:
            if len(task) == 1:
                future = self.submit(task[0])
            elif len(task) == 2:
                future = self.submit(task[0], *task[1])
            else:
                future = self.submit(task[0], *task[1], **task[2])
            futures.append(future)
        return futures
    
    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        """Waits for all queued tasks to complete.
        
        Returns:
            True if all tasks completed, False if timeout
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                queue_empty = self._queue.empty()
                no_active = self._active_tasks == 0
            
            if queue_empty and no_active:
                return True
            
            if timeout is not None and (time.time() - start_time) > timeout:
                logger.warning(
                    "Timeout waiting for pool '%s' completion",
                    self.name
                )
                return False
            
            time.sleep(0.1)
    
    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> bool:
        """
        """Shuts down the pool gracefully.
        
        Args:
            wait: Wait for in-progress tasks to finish
            timeout: Maximum wait timeout
            
        Returns:
            True if shutdown succeeded, False if timed out
        """
        logger.info("Apagando ResourcePool '%s'...", self.name)
        self._running = False
        
        # Vaciar cola
        while not self._queue.empty():
            try:
                task_data = self._queue.get_nowait()
                task_data['future'].set_exception(
                    RuntimeError(f"Pool '{self.name}' shut down before running task")
                )
            except Empty:
                break
        
        # Apagar executor
        self._executor.shutdown(wait=wait)
        
        if wait:
            return self.wait_for_completion(timeout)
        
        return True
    
    def get_metrics(self) -> PoolMetrics:
        """Retrieves current pool metrics."""
        with self._lock:
            avg_time = self._total_task_time / self._task_count if self._task_count > 0 else 0.0
            
            return PoolMetrics(
                active_tasks=self._active_tasks,
                queued_tasks=self._queue.qsize(),
                completed_tasks=self._completed_tasks,
                failed_tasks=self._failed_tasks,
                avg_task_time=avg_time,
                max_concurrent=self.max_workers
            )
    
    def _worker_loop(self):
        """Main worker loop processing queued tasks."""
        while self._running:
            try:
                # Fetch a task with timeout so we can re-check _running
                try:
                    task_data = self._queue.get(timeout=0.1)
                except Empty:
                    continue
                
                with self._lock:
                    self._queued_tasks -= 1
                    self._active_tasks += 1
                
                future = task_data['future']
                if future.set_running_or_notify_cancel():
                    try:
                        # Execute task
                        start_time = time.time()
                        result = task_data['fn'](*task_data['args'], **task_data['kwargs'])
                        elapsed = time.time() - start_time
                        
                        # Update metrics
                        with self._lock:
                            self._active_tasks -= 1
                            self._completed_tasks += 1
                            self._total_task_time += elapsed
                            self._task_count += 1
                        
                        future.set_result(result)
                        
                    except Exception as e:
                        # Record error
                        with self._lock:
                            self._active_tasks -= 1
                            self._failed_tasks += 1
                            self._task_count += 1
                        
                        logger.error(
                            "Error in pool '%s' task: %s",
                            self.name, e
                        )
                        future.set_exception(e)
                else:
                    # Task was cancelled
                    with self._lock:
                        self._active_tasks -= 1
                
                self._queue.task_done()
                
            except Exception as e:
                logger.error("Error in worker loop of pool '%s': %s", self.name, e)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)


class ResourcePoolManager:
    """Centralized manager for resource pools."""
    
    def __init__(self):
        self._pools: Dict[str, ResourcePool] = {}
        self._lock = threading.Lock()
    
    def register_pool(
        self,
        name: str,
        max_workers: int,
        max_queue_size: int = 100
    ) -> ResourcePool:
        """Registers a new resource pool."""
        with self._lock:
            if name in self._pools:
                raise ValueError(f"Pool '{name}' already registered")
            
            pool = ResourcePool(name, max_workers, max_queue_size)
            self._pools[name] = pool
            return pool
    
    def get_pool(self, name: str) -> Optional[ResourcePool]:
        """Gets a pool by name."""
        with self._lock:
            return self._pools.get(name)
    
    def shutdown_all(self, wait: bool = True, timeout: Optional[float] = None) -> bool:
        """Shuts down all pools."""
        logger.info("Shutting down all ResourcePools...")
        
        all_success = True
        for name, pool in list(self._pools.items()):
            try:
                success = pool.shutdown(wait=wait, timeout=timeout)
                if not success:
                    all_success = False
                    logger.warning("Timeout shutting down pool '%s'", name)
            except Exception as e:
                all_success = False
                logger.error("Error shutting down pool '%s': %s", name, e)
        
        return all_success
    
    def get_all_metrics(self) -> Dict[str, PoolMetrics]:
        """Returns metrics for all pools."""
        metrics = {}
        with self._lock:
            for name, pool in self._pools.items():
                metrics[name] = pool.get_metrics()
        return metrics
    
    def print_status(self):
        """Prints status of all pools."""
        metrics = self.get_all_metrics()
        
        if not metrics:
            logger.info("No pools registered")
            return
        
        logger.info("=== ResourcePool Status ===")
        for name, metric in metrics.items():
            logger.info(
                "Pool '%s': active=%d, queued=%d, completed=%d, "
                "failed=%d, avg time=%.2fs, max concurrent=%d",
                name,
                metric.active_tasks,
                metric.queued_tasks,
                metric.completed_tasks,
                metric.failed_tasks,
                metric.avg_task_time,
                metric.max_concurrent
            )

# Pools specific to the ingestion pipeline
class IngestionPools:
    """Preconfigured resource pools for ingestion."""

    def __init__(self, config: Optional[Any] = None):
        self.config = config or {}
        self.manager = ResourcePoolManager()
        
        # Default configuration
        self.convert_max_workers = self._get_config('INGESTION_CONVERT_POOL_WORKERS', 2)
        self.embed_max_workers = self._get_config('INGESTION_EMBED_POOL_WORKERS', 1)
        self.upsert_max_workers = self._get_config('INGESTION_UPSERT_POOL_WORKERS', 2)
        
        self.convert_queue_size = self._get_config('INGESTION_CONVERT_QUEUE_SIZE', 50)
        self.embed_queue_size = self._get_config('INGESTION_EMBED_QUEUE_SIZE', 100)
        self.upsert_queue_size = self._get_config('INGESTION_UPSERT_QUEUE_SIZE', 200)
        
        # Initialize pools
        self.convert_pool = self.manager.register_pool(
            'convert',
            self.convert_max_workers,
            self.convert_queue_size
        )
        
        self.embed_pool = self.manager.register_pool(
            'embed',
            self.embed_max_workers,
            self.embed_queue_size
        )
        
        self.upsert_pool = self.manager.register_pool(
            'upsert',
            self.upsert_max_workers,
            self.upsert_queue_size
        )
        
        logger.info(
            "IngestionPools initialized: Convert(%d), Embed(%d), Upsert(%d)",
            self.convert_max_workers, self.embed_max_workers, self.upsert_max_workers
        )
    
    def _get_config(self, key: str, default: Any) -> Any:
        """Gets a configuration value."""
        return getattr(self.config, key, default) if hasattr(self.config, key) else default
    
    def submit_conversion(self, task_fn: Callable, *args, **kwargs) -> Optional[Future]:
        """Submit a conversion/OCR task to the corresponding pool."""
        return self.convert_pool.submit(task_fn, *args, **kwargs)
    
    def submit_embedding(self, task_fn: Callable, *args, **kwargs) -> Optional[Future]:
        """Submit an embedding task to the corresponding pool."""
        return self.embed_pool.submit(task_fn, *args, **kwargs)
    
    def submit_upsert(self, task_fn: Callable, *args, **kwargs) -> Optional[Future]:
        """Submit an upsert task to the corresponding pool."""
        return self.upsert_pool.submit(task_fn, *args, **kwargs)
    
    def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        """Wait for all pools to complete their tasks."""
        success = True
        
        for pool_name in ['convert', 'embed', 'upsert']:
            pool = self.manager.get_pool(pool_name)
            if pool:
                if not pool.wait_for_completion(timeout):
                    logger.warning("Timeout waiting for pool '%s'", pool_name)
                    success = False
        
        return success
    
    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> bool:
        """Shut down all ingestion pools."""
        return self.manager.shutdown_all(wait=wait, timeout=timeout)
    
    def get_status(self) -> Dict[str, Any]:
        """Get the status of all pools."""
        metrics = self.manager.get_all_metrics()
        
        status = {
            'pools': {},
            'total_active': 0,
            'total_queued': 0,
            'total_completed': 0,
            'total_failed': 0
        }
        
        for name, metric in metrics.items():
            status['pools'][name] = {
                'active': metric.active_tasks,
                'queued': metric.queued_tasks,
                'completed': metric.completed_tasks,
                'failed': metric.failed_tasks,
                'avg_time': metric.avg_task_time,
                'max_concurrent': metric.max_concurrent
            }
            
            status['total_active'] += metric.active_tasks
            status['total_queued'] += metric.queued_tasks
            status['total_completed'] += metric.completed_tasks
            status['total_failed'] += metric.failed_tasks
        
        return status


# Singleton global
_global_pool_manager: Optional[ResourcePoolManager] = None
_global_ingestion_pools: Optional[IngestionPools] = None


def get_global_pool_manager() -> ResourcePoolManager:
    """Returns the global pool manager."""
    global _global_pool_manager
    if _global_pool_manager is None:
        _global_pool_manager = ResourcePoolManager()
    return _global_pool_manager


def get_global_ingestion_pools(config: Optional[Any] = None) -> IngestionPools:
    """Returns the global ingestion pools."""
    global _global_ingestion_pools
    if _global_ingestion_pools is None:
        _global_ingestion_pools = IngestionPools(config)
    return _global_ingestion_pools


def shutdown_global_pools(wait: bool = True, timeout: Optional[float] = None) -> bool:
    """Shuts down all global pools."""
    global _global_ingestion_pools, _global_pool_manager
    
    all_success = True
    
    if _global_ingestion_pools:
        if not _global_ingestion_pools.shutdown(wait=wait, timeout=timeout):
            all_success = False
    
    if _global_pool_manager:
        if not _global_pool_manager.shutdown_all(wait=wait, timeout=timeout):
            all_success = False
    
    return all_success
