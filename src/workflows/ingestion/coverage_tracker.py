"""
Dynamic code coverage tracker for ingestion pipeline.

This module provides coverage tracking during actual ingestion execution,
correlating code execution with workflow phases to identify orphaned code.
"""
import os
import sys
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import coverage
from contextlib import contextmanager

from src.workflows.query.audit import get_logger

logger = get_logger(__name__)

DEFAULT_COVERAGE_REPORTS_DIR = Path(__file__).resolve().parents[3] / "tools" / "debug" / "coverage" / "coverage_reports"


class WorkflowPhase(Enum):
    """Ingestion workflow phases for coverage correlation."""
    DISCOVER = "discovery"
    PREPROCESS = "preprocessing"
    EXTRACT = "extraction"
    EMBED = "embedding"
    STORE = "storage"
    CLEANUP = "cleanup"
    ORCHESTRATION = "orchestration"
    UNKNOWN = "unknown"


@dataclass
class CoverageDataPoint:
    """Single data point for coverage tracking."""
    filename: str
    line_number: int
    function_name: Optional[str] = None
    phase: WorkflowPhase = WorkflowPhase.UNKNOWN
    timestamp: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseCoverage:
    """Coverage data for a specific workflow phase."""
    phase: WorkflowPhase
    files_covered: Set[str] = field(default_factory=set)
    lines_covered: Set[Tuple[str, int]] = field(default_factory=set)
    functions_covered: Set[Tuple[str, str]] = field(default_factory=set)
    execution_count: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class IngestionCoverageTracker:
    """
    Tracks code coverage during ingestion pipeline execution.
    
    This tracker uses coverage.py to monitor which lines, functions, and branches
    are executed during real ingestion workflows, correlating coverage data
    with specific workflow phases.
    """
    
    def __init__(self, source_dirs: List[str], output_dir: Optional[str] = None):
        """
        Initialize the coverage tracker.
        
        Args:
            source_dirs: List of source directories to track coverage for
            output_dir: Directory to store coverage reports (default: tools/debug/coverage/coverage_reports)
        """
        self.source_dirs = [Path(d).resolve() for d in source_dirs]
        self.output_dir = Path(output_dir or DEFAULT_COVERAGE_REPORTS_DIR).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize coverage.py with branch coverage enabled
        self.cov = coverage.Coverage(
            source=[str(d) for d in self.source_dirs],
            branch=True,  # Enable branch coverage
            data_file=str(self.output_dir / ".coverage_ingestion"),
            config_file=False,
        )
        
        # Phase tracking
        self.current_phase: Optional[WorkflowPhase] = None
        self.phase_data: Dict[WorkflowPhase, PhaseCoverage] = {}
        self._phase_stack: List[WorkflowPhase] = []
        
        # Thread safety
        self._lock = threading.RLock()
        
        # File mapping for source files
        self._source_files: Set[str] = set()
        self._collect_source_files()
        
        logger.info(f"Coverage tracker initialized for {len(self.source_dirs)} source directories")
    
    def _collect_source_files(self) -> None:
        """Collect all Python source files in the source directories."""
        for source_dir in self.source_dirs:
            for py_file in source_dir.rglob("*.py"):
                if py_file.is_file():
                    self._source_files.add(str(py_file.resolve()))
        
        logger.debug(f"Found {len(self._source_files)} Python source files")
    
    def start_tracking(self) -> None:
        """Start coverage tracking."""
        with self._lock:
            self.cov.start()
            logger.info("Coverage tracking started")
    
    def stop_tracking(self) -> None:
        """Stop coverage tracking and save data."""
        with self._lock:
            self.cov.stop()
            self.cov.save()
            logger.info("Coverage tracking stopped")
    
    @contextmanager
    def track_phase(self, phase: WorkflowPhase, context: Optional[Dict[str, Any]] = None):
        """
        Context manager to track coverage within a specific workflow phase.
        
        Args:
            phase: The workflow phase to track
            context: Optional context information for this phase
        """
        self.enter_phase(phase, context)
        try:
            yield
        finally:
            self.exit_phase()
    
    def enter_phase(self, phase: WorkflowPhase, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Enter a new workflow phase for coverage tracking.
        
        Args:
            phase: The workflow phase to enter
            context: Optional context information for this phase
        """
        with self._lock:
            self._phase_stack.append(phase)
            self.current_phase = phase
            
            if phase not in self.phase_data:
                self.phase_data[phase] = PhaseCoverage(phase=phase)
            
            phase_coverage = self.phase_data[phase]
            phase_coverage.execution_count += 1
            phase_coverage.start_time = time.time()
            
            logger.debug(f"Entered coverage phase: {phase.value}")
    
    def exit_phase(self) -> None:
        """Exit the current workflow phase."""
        with self._lock:
            if not self._phase_stack:
                logger.warning("Attempted to exit phase but no phase is active")
                return
            
            phase = self._phase_stack.pop()
            self.current_phase = self._phase_stack[-1] if self._phase_stack else None
            
            if phase in self.phase_data:
                phase_coverage = self.phase_data[phase]
                phase_coverage.end_time = time.time()
                
                # Capture current coverage data for this phase
                self._capture_phase_coverage(phase_coverage)
            
            logger.debug(f"Exited coverage phase: {phase.value}")
    
    def _capture_phase_coverage(self, phase_coverage: PhaseCoverage) -> None:
        """Capture current coverage data for a phase."""
        try:
            # Get current coverage data
            data = self.cov.get_data()
            
            # Get covered lines
            for filename in self._source_files:
                lines = data.lines(filename)
                if lines:
                    for line in lines:
                        phase_coverage.lines_covered.add((filename, line))
                        phase_coverage.files_covered.add(filename)
            
            # Note: Function coverage would require more complex analysis
            # For now, we track lines and files
            
        except Exception as e:
            logger.warning(f"Failed to capture phase coverage: {e}")
    
    def get_orphaned_code(self) -> Dict[str, Any]:
        """
        Identify orphaned code (code not executed during any phase).
        
        Returns:
            Dictionary with orphaned code analysis
        """
        with self._lock:
            try:
                # Get overall coverage data
                data = self.cov.get_data()
                
                # Calculate orphaned code
                orphaned_files: List[str] = []
                orphaned_lines: Dict[str, List[int]] = {}
                
                for filename in self._source_files:
                    # Get all executable lines in the file
                    all_lines = set()
                    try:
                        # Use coverage's analysis to get executable lines
                        analysis = self.cov.analysis2(filename)
                        if analysis:
                            executable_lines = set(analysis[1])  # Executable lines
                            all_lines.update(executable_lines)
                    except Exception:
                        # Fallback: try to get lines from the file
                        try:
                            with open(filename, 'r') as f:
                                total_lines = len(f.readlines())
                                all_lines = set(range(1, total_lines + 1))
                        except Exception:
                            continue
                    
                    # Get covered lines
                    covered_lines = set(data.lines(filename) or [])
                    
                    # Calculate orphaned lines
                    orphaned = all_lines - covered_lines
                    if orphaned:
                        orphaned_lines[filename] = sorted(orphaned)
                    
                    # Check if file is completely orphaned
                    if not covered_lines and all_lines:
                        orphaned_files.append(filename)
                
                return {
                    "orphaned_files": orphaned_files,
                    "orphaned_lines": orphaned_lines,
                    "total_files": len(self._source_files),
                    "total_orphaned_files": len(orphaned_files),
                    "total_orphaned_lines": sum(len(lines) for lines in orphaned_lines.values()),
                }
                
            except Exception as e:
                logger.error(f"Failed to analyze orphaned code: {e}")
                return {
                    "orphaned_files": [],
                    "orphaned_lines": {},
                    "total_files": 0,
                    "total_orphaned_files": 0,
                    "total_orphaned_lines": 0,
                    "error": str(e),
                }
    
    def generate_reports(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Generate comprehensive coverage reports.
        
        Args:
            output_dir: Directory to store reports (default: self.output_dir)
            
        Returns:
            Dictionary with report file paths
        """
        report_dir = Path(output_dir or self.output_dir).resolve()
        report_dir.mkdir(parents=True, exist_ok=True)
        
        with self._lock:
            # Generate standard coverage reports
            self.cov.save()
            
            # Text report
            text_report_path = report_dir / "coverage_report.txt"
            with open(text_report_path, 'w') as f:
                self.cov.report(file=f)
            
            # HTML report
            html_report_dir = report_dir / "html"
            self.cov.html_report(directory=str(html_report_dir))
            
            # JSON report with phase data
            json_report_path = report_dir / "coverage_analysis.json"
            analysis = self._generate_analysis_report()
            with open(json_report_path, 'w') as f:
                json.dump(analysis, f, indent=2, default=str)
            
            # Orphaned code report
            orphaned_report_path = report_dir / "orphaned_code.json"
            orphaned_analysis = self.get_orphaned_code()
            with open(orphaned_report_path, 'w') as f:
                json.dump(orphaned_analysis, f, indent=2)
            
            logger.info(f"Coverage reports generated in {report_dir}")
            
            return {
                "text_report": str(text_report_path),
                "html_report": str(html_report_dir / "index.html"),
                "json_analysis": str(json_report_path),
                "orphaned_code": str(orphaned_report_path),
            }
    
    def _generate_analysis_report(self) -> Dict[str, Any]:
        """Generate detailed analysis report with phase correlation."""
        analysis = {
            "timestamp": time.time(),
            "source_directories": [str(d) for d in self.source_dirs],
            "phases": {},
            "summary": {},
        }
        
        # Calculate phase coverage statistics
        total_files = len(self._source_files)
        phase_stats = {}
        
        for phase, phase_data in self.phase_data.items():
            files_covered = len(phase_data.files_covered)
            lines_covered = len(phase_data.lines_covered)
            
            phase_stats[phase.value] = {
                "files_covered": files_covered,
                "files_coverage_percent": (files_covered / total_files * 100) if total_files > 0 else 0,
                "lines_covered": lines_covered,
                "execution_count": phase_data.execution_count,
                "duration_seconds": (phase_data.end_time - phase_data.start_time) 
                    if phase_data.start_time and phase_data.end_time else None,
            }
        
        analysis["phases"] = phase_stats
        
        # Overall summary
        try:
            data = self.cov.get_data()
            summary = self.cov.report()
            analysis["summary"] = {
                "total_statements": data.numb_statements(),
                "total_missing": data.numb_missing(),
                "total_branches": data.numb_branches(),
                "total_missing_branches": data.numb_missing_branches(),
                "coverage_percent": data.covered_percent(),
            }
        except Exception as e:
            analysis["summary"]["error"] = str(e)
        
        return analysis
    
    def clear(self) -> None:
        """Clear all coverage data."""
        with self._lock:
            self.cov.erase()
            self.phase_data.clear()
            self._phase_stack.clear()
            self.current_phase = None
            logger.info("Coverage data cleared")


# Global coverage tracker instance
_global_tracker: Optional[IngestionCoverageTracker] = None


def init_global_coverage_tracker(source_dirs: Optional[List[str]] = None, 
                                output_dir: Optional[str] = None) -> IngestionCoverageTracker:
    """
    Initialize global coverage tracker.
    
    Args:
        source_dirs: Source directories to track (default: ['src'])
        output_dir: Output directory for reports (default: 'tools/debug/coverage/coverage_reports')
        
    Returns:
        Initialized coverage tracker
    """
    global _global_tracker
    
    if source_dirs is None:
        source_dirs = ['src']
    
    _global_tracker = IngestionCoverageTracker(source_dirs, output_dir)
    return _global_tracker


def get_global_coverage_tracker() -> Optional[IngestionCoverageTracker]:
    """Get the global coverage tracker instance."""
    return _global_tracker


def start_coverage_tracking() -> bool:
    """Start global coverage tracking."""
    tracker = get_global_coverage_tracker()
    if tracker:
        tracker.start_tracking()
        return True
    return False


def stop_coverage_tracking() -> bool:
    """Stop global coverage tracking and generate reports."""
    tracker = get_global_coverage_tracker()
    if tracker:
        tracker.stop_tracking()
        return True
    return False


@contextmanager
def coverage_phase(phase: WorkflowPhase, context: Optional[Dict[str, Any]] = None):
    """
    Context manager for tracking coverage in a specific phase.
    
    Example:
        with coverage_phase(WorkflowPhase.DISCOVER):
            # Discovery code here
    """
    tracker = get_global_coverage_tracker()
    if tracker:
        with tracker.track_phase(phase, context):
            yield
    else:
        yield  # No-op if tracker not initialized


def generate_coverage_reports(output_dir: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Generate coverage reports using global tracker."""
    tracker = get_global_coverage_tracker()
    if tracker:
        return tracker.generate_reports(output_dir)
    return None


def get_orphaned_code_analysis() -> Optional[Dict[str, Any]]:
    """Get orphaned code analysis using global tracker."""
    tracker = get_global_coverage_tracker()
    if tracker:
        return tracker.get_orphaned_code()
    return None
