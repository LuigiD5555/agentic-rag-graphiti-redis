"""Adaptive hybrid scanner with resumable, parallelizable, and auto-adjustable capabilities.

Implements the hybrid scan method described in docs/SCAN_ADAPTIVE_HYBRID_PLAN.md.
"""

import os
import time
import uuid
import threading
import queue
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


@dataclass
class DirectoryState:
    """State information for directory pruning."""
    mtime: float
    entry_count: int
    options_hash: str = ""
    scan_time: float = 0.0


@dataclass
class ScanMetrics:
    """Comprehensive scan metrics."""
    run_id: str
    root: str
    options_hash: str
    started_at: float
    last_checkpoint_at: float = 0.0
    completed_at: float = 0.0
    dirs_scanned_total: int = 0
    dirs_skipped_unchanged: int = 0
    dirs_skipped_visited: int = 0
    files_emitted_total: int = 0
    frontier_pending_peak: int = 0
    workers_current: int = 0
    resume_count: int = 0
    checkpoint_commits_count: int = 0
    time_to_first_file: float = 0.0


class AdaptiveHybridScanner:
    """Main adaptive hybrid scanner implementation."""
    
    def __init__(
        self,
        cache_manager: DiscoveryCacheManager,
        pattern_matcher: PatternMatcher,
        scan_checkpointer: Optional[ScanCheckpointer] = None,
        scheduler_policy: SchedulerPolicy = SchedulerPolicy.PRIORITY,
        enable_parallel: bool = True,
        max_workers: int = 4
    ):
        self.cache_manager = cache_manager
        self.pattern_matcher = pattern_matcher
        self.scan_checkpointer = scan_checkpointer
        self.scheduler_policy = scheduler_policy
        self.enable_parallel = enable_parallel
        self.max_workers = max_workers
        
        # Worker pool
        self.worker_pool: Optional[ThreadPoolExecutor] = None
        self.worker_futures: List[Future] = []
        
        # State
        self.current_run_id: Optional[str] = None
        self.metrics: Optional[ScanMetrics] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        
        # Directory state store
        self.dir_state_store: Dict[str, DirectoryState] = {}
        
        log.info(
            "AdaptiveHybridScanner initialized (policy=%s, parallel=%s, max_workers=%d)",
            scheduler_policy.value, enable_parallel, max_workers
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
            dirs_scanned = self._scan_loop(
                root=root,
                filters=filters,
                excluded_globs=excluded_globs,
                follow_symlinks=follow_symlinks,
                files=files,
                progress_every=progress_every,
                options_hash=options_hash
            )
            
            # Mark run as completed
            self._complete_run(files, dirs_scanned)
            
        except Exception as e:
            log.error("Scan interrupted: %s", e)
            if self.scan_checkpointer:
                self.scan_checkpointer.complete_run(run_id, status="interrupted")
            raise
        
        finally:
            self._cleanup()
        
        return dirs_scanned, run_id
    
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
        
        self.worker_pool = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="scan_worker"
        )
        self.worker_futures = []
        
        log.info("Worker pool initialized with %d workers", self.max_workers)
    
    def _scan_loop(
        self,
        root: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        progress_every: int,
        options_hash: str
    ) -> int:
        """Main scanning loop."""
        # Initialize frontier based on scheduler policy
        frontier = self._create_frontier()
        visited_dirs: Set[str] = set()
        
        # Add root to frontier
        root_state = self._get_directory_state(root)
        self._add_to_frontier(frontier, root, "", 0, root_state)
        
        dirs_scanned = 0
        first_file_emitted = False
        
        while not self._stop_event.is_set() and not self._is_frontier_empty(frontier):
            # Process directories
            if self.enable_parallel and self.worker_pool:
                dirs_scanned += self._process_parallel(
                    frontier, visited_dirs, filters, excluded_globs,
                    follow_symlinks, files, options_hash
                )
            else:
                dirs_scanned += self._process_sequential(
                    frontier, visited_dirs, filters, excluded_globs,
                    follow_symlinks, files, options_hash
                )
            
            # Update metrics
            self._update_metrics(frontier, visited_dirs, files, dirs_scanned)
            
            # Checkpoint periodically
            if time.time() - self.metrics.last_checkpoint_at > 30:
                self._checkpoint(files)
            
            # Progress logging
            now = time.time()
            if progress_every and dirs_scanned % progress_every == 0:
                frontier_size = self._get_frontier_size(frontier)
                log.info(
                    "Scanning... dirs=%d, files=%d, pending=%d",
                    dirs_scanned, len(files), frontier_size
                )
            
            # Track time to first file
            if not first_file_emitted and len(files) > 0:
                self.metrics.time_to_first_file = now - self.metrics.started_at
                first_file_emitted = True
            
            # Small sleep to prevent busy waiting
            time.sleep(0.01)
        
        return dirs_scanned
    
    def _create_frontier(self):
        """Create frontier based on scheduler policy."""
        if self.scheduler_policy == SchedulerPolicy.DFS:
            return []  # Use as LIFO stack
        elif self.scheduler_policy == SchedulerPolicy.BFS:
            return queue.Queue()  # Use as FIFO queue
        else:  # PRIORITY
            return []  # Use as heap
    
    def _get_directory_state(self, dirpath: str) -> DirectoryState:
        """Get directory state for pruning."""
        try:
            stat = os.stat(dirpath)
            entries = os.listdir(dirpath)
            return DirectoryState(
                mtime=stat.st_mtime,
                entry_count=len(entries)
            )
        except (OSError, PermissionError):
            return DirectoryState(mtime=0, entry_count=0)
    
    def _add_to_frontier(self, frontier, dirpath: str, rel_dirpath: str, depth: int, state: DirectoryState):
        """Add directory to frontier based on scheduler policy."""
        if self.scheduler_policy == SchedulerPolicy.DFS:
            frontier.append((dirpath, rel_dirpath, depth))
        elif self.scheduler_policy == SchedulerPolicy.BFS:
            frontier.put((dirpath, rel_dirpath, depth))
        else:  # PRIORITY
            # Calculate priority: higher mtime = more recent = higher priority
            # Lower depth = higher priority
            priority = state.mtime - (depth * 1000)
            heapq.heappush(frontier, (-priority, dirpath, rel_dirpath, depth))
    
    def _pop_from_frontier(self, frontier):
        """Pop directory from frontier based on scheduler policy."""
        if self.scheduler_policy == SchedulerPolicy.DFS:
            return frontier.pop() if frontier else None
        elif self.scheduler_policy == SchedulerPolicy.BFS:
            try:
                return frontier.get_nowait()
            except queue.Empty:
                return None
        else:  # PRIORITY
            if frontier:
                priority, dirpath, rel_dirpath, depth = heapq.heappop(frontier)
                return (dirpath, rel_dirpath, depth)
            return None
    
    def _is_frontier_empty(self, frontier) -> bool:
        """Check if frontier is empty."""
        if self.scheduler_policy == SchedulerPolicy.DFS:
            return len(frontier) == 0
        elif self.scheduler_policy == SchedulerPolicy.BFS:
            return frontier.empty()
        else:  # PRIORITY
            return len(frontier) == 0
    
    def _get_frontier_size(self, frontier) -> int:
        """Get frontier size."""
        if self.scheduler_policy == SchedulerPolicy.DFS:
            return len(frontier)
        elif self.scheduler_policy == SchedulerPolicy.BFS:
            return frontier.qsize()
        else:  # PRIORITY
            return len(frontier)
    
    def _process_sequential(
        self,
        frontier,
        visited_dirs: Set[str],
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        options_hash: str
    ) -> int:
        """Process directories sequentially."""
        dirs_scanned = 0
        dir_info = self._pop_from_frontier(frontier)
        
        if not dir_info:
            return 0
        
        dirpath, rel_dirpath, depth = dir_info
        
        # Check if already visited
        if dirpath in visited_dirs:
            self.metrics.dirs_skipped_visited += 1
            return 0
        
        visited_dirs.add(dirpath)
        
        # Check cache
        cached = self.cache_manager.is_dir_unchanged(dirpath, options_hash)
        if cached:
            self.cache_manager.record_hit()
            files.extend(cached.files)
            self.metrics.dirs_skipped_unchanged += 1
            return 1
        
        self.cache_manager.record_miss()
        dirs_scanned += 1
        
        # Scan directory
        dir_files: list[str] = []
        subdirs_to_add = []
        
        try:
            with os.scandir(dirpath) as entries:
                for entry in entries:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                        
                        if is_dir:
                            new_rel = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"
                            
                            # Check exclusion
                            if self.pattern_matcher.matches_any_glob(
                                new_rel, excluded_globs, absolute_path=entry.path
                            ):
                                continue
                            
                            # Apply filters
                            if all(s.allow_dir(rel_dirpath, entry.name, entry.path) for s in filters):
                                subdir_state = self._get_directory_state(entry.path)
                                subdirs_to_add.append((entry.path, new_rel, depth + 1, subdir_state))
                        else:
                            # Process file
                            relative_file = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"
                            
                            if self.pattern_matcher.matches_any_glob(
                                relative_file, excluded_globs, absolute_path=entry.path
                            ):
                                continue
                            
                            if all(s.allow_file(rel_dirpath, entry.name, entry.path) for s in filters):
                                files.append(entry.path)
                                dir_files.append(entry.path)
                    
                    except (OSError, PermissionError):
                        continue
            
            # Cache results
            self.cache_manager.cache_directory(dirpath, dir_files, options_hash)
            
            # Add subdirectories to frontier
            for subdir_path, subdir_rel, subdir_depth, subdir_state in subdirs_to_add:
                self._add_to_frontier(frontier, subdir_path, subdir_rel, subdir_depth, subdir_state)
        
        except (OSError, PermissionError):
            pass
        
        return dirs_scanned
    
    def _process_parallel(
        self,
        frontier,
        visited_dirs: Set[str],
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        options_hash: str
    ) -> int:
        """Process directories in parallel."""
        if not self.worker_pool:
            return 0
        
        # Submit tasks for available workers
        tasks = []
        while len(tasks) < self.max_workers and not self._is_frontier_empty(frontier):
            dir_info = self._pop_from_frontier(frontier)
            if dir_info:
                dirpath, rel_dirpath, depth = dir_info
                
                # Skip if already visited
                if dirpath in visited_dirs:
                    self.metrics.dirs_skipped_visited += 1
                    continue
                
                visited_dirs.add(dirpath)
                task = self.worker_pool.submit(
                    self._scan_directory_worker,
                    dirpath, rel_dirpath, depth, filters, excluded_globs,
                    follow_symlinks, options_hash
                )
                tasks.append((task, dirpath))
        
        # Wait for tasks to complete
        dirs_scanned = 0
        for task, dirpath in tasks:
            try:
                result = task.result(timeout=30)
                if result:
                    dir_files, subdirs = result
                    files.extend(dir_files)
                    
                    # Cache results
                    self.cache_manager.cache_directory(dirpath, dir_files, options_hash)
                    
                    # Add subdirectories to frontier
                    for subdir_path, subdir_rel, subdir_depth, subdir_state in subdirs:
                        self._add_to_frontier(frontier, subdir_path, subdir_rel, subdir_depth, subdir_state)
                    
                    dirs_scanned += 1
            except Exception as e:
                log.debug("Error scanning directory %s: %s", dirpath, e)
        
        return dirs_scanned
    
    def _scan_directory_worker(
        self,
        dirpath: str,
        rel_dirpath: str,
        depth: int,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        options_hash: str
    ) -> Optional[Tuple[List[str], List[Tuple[str, str, int, DirectoryState]]]]:
        """Worker function for parallel directory scanning."""
        # Check cache first
        cached = self.cache_manager.is_dir_unchanged(dirpath, options_hash)
        if cached:
            self
