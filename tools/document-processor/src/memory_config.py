"""
Memory configuration and optimization for document processing.
"""

import os
import psutil
from typing import Dict, Any


def get_system_memory_info() -> Dict[str, Any]:
    """
    Get information about system memory.
    
    Returns:
        Dictionary with memory information
    """
    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            'total_memory_gb': mem.total / (1024**3),
            'available_memory_gb': mem.available / (1024**3),
            'used_memory_gb': mem.used / (1024**3),
            'memory_percent': mem.percent,
            'total_swap_gb': swap.total / (1024**3),
            'used_swap_gb': swap.used / (1024**3),
            'swap_percent': swap.percent,
        }
    except Exception:
        # Fallback if psutil is not available
        return {
            'total_memory_gb': 8.0,  # Assume 8GB default
            'available_memory_gb': 4.0,
            'used_memory_gb': 4.0,
            'memory_percent': 50.0,
            'total_swap_gb': 4.0,
            'used_swap_gb': 1.0,
            'swap_percent': 25.0,
        }


def get_recommended_memory_limits() -> Dict[str, str]:
    """
    Get recommended memory limits based on system memory.
    
    Returns:
        Dictionary with recommended memory limits
    """
    mem_info = get_system_memory_info()
    total_memory_gb = mem_info['total_memory_gb']
    
    if total_memory_gb >= 16:
        # High memory system (16GB+)
        return {
            'libreoffice_memory': '4G',
            'tesseract_memory': '2G',
            'pandas_memory': '2G',
            'max_file_size_mb': '200',
            'concurrent_processes': '4',
        }
    elif total_memory_gb >= 8:
        # Medium memory system (8-16GB)
        return {
            'libreoffice_memory': '2G',
            'tesseract_memory': '1G',
            'pandas_memory': '1G',
            'max_file_size_mb': '100',
            'concurrent_processes': '3',
        }
    else:
        # Low memory system (<8GB)
        return {
            'libreoffice_memory': '1G',
            'tesseract_memory': '512M',
            'pandas_memory': '512M',
            'max_file_size_mb': '50',
            'concurrent_processes': '2',
        }


def optimize_memory_usage():
    """
    Apply memory optimizations for document processing.
    """
    recommendations = get_recommended_memory_limits()
    
    # Set environment variables for LibreOffice
    os.environ['URE_BOOTSTRAP'] = 'vnd.sun.star.pathname:/usr/lib/libreoffice/program/fundamentalrc'
    
    # Set Java memory limits (used by some LibreOffice components)
    os.environ['JAVA_TOOL_OPTIONS'] = f'-Xmx{recommendations["libreoffice_memory"]} -Xms256M'
    
    # Set Python memory limits
    os.environ['PYTHONMALLOC'] = 'malloc'
    
    # Log memory configuration
    print("Memory configuration applied:")
    print(f"  LibreOffice memory: {recommendations['libreoffice_memory']}")
    print(f"  Tesseract memory: {recommendations['tesseract_memory']}")
    print(f"  Max file size: {recommendations['max_file_size_mb']}MB")
    print(f"  Concurrent processes: {recommendations['concurrent_processes']}")


def check_memory_available(min_memory_gb: float = 1.0) -> bool:
    """
    Check if minimum memory is available.
    
    Args:
        min_memory_gb: Minimum required memory in GB
        
    Returns:
        True if enough memory is available
    """
    mem_info = get_system_memory_info()
    available_gb = mem_info['available_memory_gb']
    
    if available_gb >= min_memory_gb:
        return True
    
    print(f"Warning: Only {available_gb:.1f}GB memory available, need {min_memory_gb}GB")
    return False


def get_process_memory_usage() -> Dict[str, float]:
    """
    Get memory usage of current process.
    
    Returns:
        Dictionary with process memory information
    """
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        
        return {
            'rss_mb': mem_info.rss / (1024**2),  # Resident Set Size
            'vms_mb': mem_info.vms / (1024**2),  # Virtual Memory Size
            'percent': process.memory_percent(),
        }
    except Exception:
        return {
            'rss_mb': 0,
            'vms_mb': 0,
            'percent': 0,
        }


class MemoryMonitor:
    """
    Monitor memory usage during document processing.
    """
    
    def __init__(self, warning_threshold_mb: float = 1024):
        """
        Initialize memory monitor.
        
        Args:
            warning_threshold_mb: Memory warning threshold in MB
        """
        self.warning_threshold_mb = warning_threshold_mb
        self.peak_usage_mb = 0
        
    def check_memory(self) -> bool:
        """
        Check current memory usage.
        
        Returns:
            True if memory usage is below warning threshold
        """
        usage = get_process_memory_usage()
        current_usage_mb = usage['rss_mb']
        
        # Update peak usage
        if current_usage_mb > self.peak_usage_mb:
            self.peak_usage_mb = current_usage_mb
        
        # Check warning threshold
        if current_usage_mb > self.warning_threshold_mb:
            print(f"Warning: High memory usage: {current_usage_mb:.1f}MB")
            return False
        
        return True
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get memory usage summary.
        
        Returns:
            Dictionary with memory summary
        """
        usage = get_process_memory_usage()
        system_info = get_system_memory_info()
        
        return {
            'process_rss_mb': usage['rss_mb'],
            'process_vms_mb': usage['vms_mb'],
            'process_percent': usage['percent'],
            'peak_usage_mb': self.peak_usage_mb,
            'system_available_gb': system_info['available_memory_gb'],
            'system_used_percent': system_info['memory_percent'],
        }
