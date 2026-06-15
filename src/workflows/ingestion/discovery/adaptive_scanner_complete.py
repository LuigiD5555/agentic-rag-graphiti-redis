"""Adaptive hybrid scanner with resumable, parallelizable, and auto-adjustable capabilities.

Implements the hybrid scan method described in docs/SCAN_ADAPTIVE_HYBRID_PLAN.md.
Features:
1. Resumable scanning with run_id persistence
2. DirectoryState-based pruning (skip unchanged directories)
3. Configurable scheduler (DFS/BFS/PriorityQueue)
4. Parallel directory scanning with adaptive concurrency control
5. Backpressure integration based on system resources
6. Comprehensive metrics collection
"""

import os
import time
import uuid
import threading
import queue
import psutil
from typing import List, Set, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import heapq
from concurrent.futures import ThreadPoolExecutor, Future, as_completed

from src.workflows.query.audit import get_logger
from src.workflows.ingestion.discovery.cache import DiscoveryCacheManager
from src.workflows.ingestion.discovery.pattern_matching import PatternMatcher
from src.workflows.ingestion.checkpoint.scan_checkpointer import ScanCheckpointer, ScanRun

log = get_logger(__name__)


class SchedulerPolicy(Enum):
    """Scheduling policies for directory traversal."""
    DFS = "dfs"  # Depth-first search (LIFO)
    BFS = "bfs"  # Breadth-first search (FIFO)
    PRIORITY = "priority"  # Priority queue based on scoring


@dataclass(order=True)
class PriorityDirectory:
    """Directory entry for priority queue scheduling."""
    priority: float
    dirpath: str = field(compare=False)
    rel_dirpath: str = field(compare=False)
    depth: int = field(compare=False)
    mtime: float = field(compare=False)
    entry_count: int = field(compare=False)


@dataclass
class DirectoryState:
    """State information for directory pruning."""
    mtime: float
    entry_count: int
    max_child_mtime: Optional[float] = None
    options_hash: str = ""
    scan_time: float = 0.0


@dataclass
class SystemMetrics:
    """System resource metrics for adaptive control."""
    ram_percent: float
    cpu_load: float
    disk_percent: float
    io_pressure: float  # 0-1 scale, higher = more pressure
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScanMetrics:
    """Comprehensive scan metrics."""
    # Run identification
    run_id: str
    root: str
    options_hash: str
    
    # Timing
    started_at: float
    last_checkpoint_at: float = 0.0
    completed_at: float = 0.0
    
    # Progress
    dirs_scanned_total: int = 0
    dirs_skipped_unchanged: int = 0
    dirs_skipped_visited: int = 0
    files_emitted_total: int = 0
    
    # Frontier
    frontier_pending_peak: int = 0
    frontier_size_current: int = 0
    
    # Workers
    workers_min: int = 0
    workers_avg: float = 0.0
    workers_max: int = 0
    workers_current: int = 0
    
    # Resume
    resume_count: int = 0
    checkpoint_commits_count: int = 0
    
    # Performance
    time_to_first_file: float = 0.0
    scan_duration_seconds: float = 0.0
    
    # System pressure (sampled)
    ram_percent_samples: List[float] = field(default_factory=list)
    cpu_load_samples: List[float] = field(default_factory=list)
    disk_percent_samples: List[float] = field(default_factory=list)
    io_pressure_samples: List[float] = field(default_factory=list)


class AdaptiveConcurrencyController:
    """Adaptive worker pool controller based on system pressure."""
    
    def __init__(
        self,
        baseline_workers: int = 2,
        max_workers: int = 8,
        ram_low_threshold: float = 65.0,
        ram_high_threshold: float = 85.0,
        disk_watermark: float = 70.0,
        io_threshold: float = 0.8,
        hysteresis_cycles_up: int = 3,
        hysteresis_cycles_down: int = 2,
        check_interval: float = 2.0
    ):
        self.baseline_workers = baseline_workers
        self.max_workers = max_workers
        self.ram_low_threshold = ram_low_threshold
        self.ram_high_threshold = ram_high_threshold
        self.disk_watermark = disk_watermark
        self.io_threshold = io_threshold
        self.hysteresis_cycles_up = hysteresis_cycles_up
        self.hysteresis_cycles_down = hysteresis_cycles_down
        self.check_interval = check_interval
        
        self.current_workers = baseline_workers
        self.condition_up = 0
        self.condition_down = 0
        self.last_check = time.time()
        
        # Track system metrics
        self.metrics_history: List[SystemMetrics] = []
        self.max_history_size = 100
        
    def get_system_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        ram_percent = psutil.virtual_memory().percent
        cpu_load = psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else psutil.cpu_percent(interval=0.1)
        
        # Get disk usage for staging area
        try:
            disk_usage = psutil.disk_usage('/tmp').percent
        except Exception:
            disk_usage = psutil.disk_usage('.').percent
        
        # Simple IO pressure indicator (disk busy time)
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                busy_time = getattr(disk_io, 'busy_time', 0)
                read_time = getattr(disk_io, 'read_time', 0)
                write_time = getattr(disk_io, 'write_time', 0)
                io_pressure = min(1.0, busy_time / (busy_time + read_time + write_time + 1))
            else:
                io_pressure = 0.0
        except Exception:
            io_pressure = 0.0
        
        return SystemMetrics(
            ram_percent=ram_percent,
            cpu_load=cpu_load,
            disk_percent=disk_usage,
            io_pressure=io_pressure
        )
    
    def should_increase_workers(self, metrics: SystemMetrics) -> bool:
        """Check if we should increase worker count."""
        return (
            metrics.ram_percent < self.ram_low_threshold and
            metrics.disk_percent < self.disk_watermark and
            metrics.io_pressure < self.io_threshold and
            self.current_workers < self.max_workers
        )
    
    def should_decrease_workers(self, metrics: SystemMetrics) -> bool:
        """Check if we should decrease worker count."""
        # Hard limits (emergency)
        if metrics.ram_percent > self.ram_high_threshold:
            return True
        if metrics.disk_percent > self.disk_watermark:
            return True
        if metrics.io_pressure > self.io_threshold:
            return True
        
        # Soft limits (gradual adjustment)
        if metrics.ram_percent > self.ram_low_threshold + 10:
            return True
        if metrics.cpu_load > 4.0:  # High load average
            return True
            
        return False
    
    def update_workers(self) -> int:
        """Update worker count based on system conditions."""
        now = time.time()
        if now - self.last_check < self.check_interval:
            return self.current_workers
        
        self.last_check = now
        metrics = self.get_system_metrics()
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history.pop(0)
        
        if self.should_increase_workers(metrics):
            self.condition_up += 1
            self.condition_down = 0
            
            if self.condition_up >= self.hysteresis_cycles_up:
                self.current_workers = min(self.current_workers + 1, self.max_workers)
                self.condition_up = 0
                log.info(
                    "Increasing workers to %d (RAM=%.1f%%, Disk=%.1f%%)",
                    self.current_workers, metrics.ram_percent, metrics.disk_percent
                )
        
        elif self.should_decrease_workers(metrics):
            self.condition_down += 1
            self.condition_up = 0
            
            if self.condition_down >= self.hysteresis_cycles_down:
                # Emergency reduction for hard limits
                if metrics.ram_percent > self.ram_high_threshold:
                    reduction = max(1, self.current_workers // 2)
                else:
                    reduction = 1
                
                self.current_workers = max(1, self.current_workers - reduction)
                self.condition_down = 0
                log.info(
                    "Decreasing workers to %d (RAM=%.1f%%, Disk=%.1f%%, IO=%.2f)",
                    self.current_workers, metrics.ram_percent,
                    metrics.disk_percent, metrics.io_pressure
                )
        
        else:
            # Reset counters when conditions are neutral
            self.condition_up = 0
            self.condition_down = 0
        
        return self.current_workers
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get controller metrics."""
        if not self.metrics_history:
            return {}
        
        latest = self.metrics_history[-1]
        return {
            'current_workers': self.current_workers,
            'ram_percent': latest.ram_percent,
            'cpu_load': latest.cpu_load,
            'disk_percent': latest.disk_percent,
            'io_pressure': latest.io_pressure,
            'condition_up': self.condition_up,
            'condition_down': self.condition_down
        }


class AdaptiveHybridScanner:
    """Main adaptive hybrid scanner implementation."""
    
    def __init__(
        self,
        cache_manager: DiscoveryCacheManager,
        pattern_matcher: PatternMatcher,
        scan_checkpointer: Optional[ScanCheckpointer] = None,
        scheduler_policy: SchedulerPolicy = SchedulerPolicy.PRIORITY,
        enable_parallel: bool = True,
        enable_adaptive: bool = True
    ):
        self.cache_manager = cache_manager
        self.pattern_matcher = pattern_matcher
        self.scan_checkpointer = scan_checkpointer
        self.scheduler_policy = scheduler_policy
        self.enable_parallel = enable_parallel
        self.enable_adaptive = enable_adaptive
        
        # Adaptive controller
        self.concurrency_controller = AdaptiveConcurrencyController() if enable_adaptive else None
        
        # Worker pool
        self.worker_pool: Optional[ThreadPoolExecutor] = None
        self.worker_futures: List[Future] = []
        
        # State
        self.current_run_id: Optional[str] = None
        self.metrics: Optional[ScanMetrics] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        
        # Directory state store (in-memory for now, could be persisted)
        self.dir_state_store: Dict[str, DirectoryState] = {}
        
        log.info(
            "AdaptiveHybridScanner initialized (policy=%s, parallel=%s, adaptive=%s)",
            scheduler_policy.value, enable_parallel, enable_adaptive
        )
    
    def scan_directory(
        self,
        root: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        progress_every: int,
        options_hash: str,
        run_id: Optional[str] = None
    ) -> Tuple[int, str]:
        """
        Scan directory using adaptive hybrid method.
        
        Returns:
            Tuple of (dirs_scanned, run_id)
        """
        # Initialize or resume run
        if run_id and self.scan_checkpointer:
            scan_run = self.scan_checkpointer.resume_run(run_id)
            if scan_run:
                self.current_run_id = run_id
                self.metrics = self._load_metrics_from_run(scan_run)
                self.metrics.resume_count += 1
                log.info("Resuming scan run %s", run_id)
            else:
                run_id = None
        
        if not run_id:
            run_id = self._start_new_run(root, options_hash)
        
        # Initialize metrics
        if not self.metrics:
            self.metrics = ScanMetrics(
                run_id=run_id,
                root=root,
                options_hash=options_hash,
                started_at=time.time(),
                time_to_first_file=float('inf')
            )
        
        # Initialize worker pool if parallel mode enabled
        if self.enable_parallel:
            self._initialize_worker_pool()
        
        try:
            # Main scanning loop
            self._scan_loop(
                root=root,
                filters=filters,
                excluded_globs=excluded_globs,
                follow_symlinks=follow_symlinks,
                files=files,
                progress_every=progress_every,
                options_hash=options_hash
            )
            
            # Mark run as completed
            self._complete_run(files)
            
        except Exception as e:
            log.error("Scan interrupted: %s", e)
            if self.scan_checkpointer:
                self.scan_checkpointer.complete_run(run_id, status="interrupted")
            raise
        
        finally:
            self._cleanup()
        
        return self.metrics.dirs_scanned_total, run_id
    
    def _start_new_run(self, root: str, options_hash: str) -> str:
        """Start a new scan run."""
        if self.scan_checkpointer:
            run_id = self.scan_checkpointer.start_new_run([root], options_hash)
        else:
            run_id = f"adaptive_{uuid.uuid4().hex[:12]}_{int(time.time())}"
        
        self.current_run_id = run_id
        log.info("Started new adaptive scan run %s", run_id)
        return run_id
    
    def _load_metrics_from_run(self, scan_run: ScanRun) -> ScanMetrics:
        """Load metrics from a resumed scan run."""
        return ScanMetrics(
            run_id=scan_run.run_id,
            root=scan_run.root_paths[0] if scan_run.root_paths else "",
            options_hash=scan_run.options_hash,
            started_at=scan_run.started_at,
            dirs_scanned_total=scan_run.dirs_scanned,
            files_emitted_total=scan_run.files_found,
            resume_count=1
        )
    
    def _initialize_worker_pool(self):
        """Initialize the worker thread pool."""
        if self.worker_pool:
            self.worker_pool.shutdown(wait=False)
        
        worker_count = 2  # Default baseline
        if self.concurrency_controller:
            worker_count = self.concurrency_controller.current_workers
        
        self.worker_pool = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="scan_worker"
        )
        self.worker_futures = []
        
        log.info("Worker pool initialized with %d workers", worker_count)
    
    def _scan_loop(
        self,
        root: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        progress_every: int,
        options_hash: str
    ):
        """Main scanning loop with adaptive control."""
        # Initialize frontier based on scheduler policy
        frontier = self._create_frontier()
        visited_dirs: Set[str] = set()
        
        # Add root to frontier
        root_state = self._get_directory_state(root)
        self._add_to_frontier(frontier, root, "", 0, root_state)
        
        first_file_emitted = False
        
        while not self._stop_event.is_set() and not self._is_frontier_empty(frontier):
            # Update adaptive worker count
            if self.enable_adaptive and self.concurrency_controller:
                new_worker_count = self.concurrency_controller.update_workers()
                if new_worker_count != len(self.worker_futures):
                    self._adjust_worker_pool(new_worker_count)
            
            # Process directories
            if self.enable_parallel and self.worker_pool:
                self._process_parallel(
                    frontier, visited_dirs, filters, excluded_globs,
                    follow_symlinks, files, options_hash
                )
            else:
                self._process_sequential(
                    frontier, visited_dirs, filters, excluded_globs,
                    follow_symlinks, files, options_hash
                )
            
            # Update metrics
            self._update_metrics(frontier, visited_dirs, files)
            
            # Checkpoint periodically
            if time.time() - self.metrics.last_checkpoint_at > 30:  # Every 30 seconds
                self._checkpoint(files)
            
            # Progress logging
            now = time.time()
            if progress_every and self.metrics.dirs_scanned_total % progress_every == 0:
                log.info(
                    "Scanning... dirs=%d, files=%d, pending=%d, workers=%d",
                    self.metrics.dirs_scanned_total,
                    self.metrics.files_emitted_total,
                    self.metrics.frontier_size_current,
                    self.metrics.workers_current
                )
            
            # Track time to first file
            if not first_file_emitted and self.metrics.files_emitted_total > 0:
                self.metrics.time_to_first_file = now - self.metrics.started_at
                first_file_emitted = True
            
            # Small sleep to prevent busy waiting
