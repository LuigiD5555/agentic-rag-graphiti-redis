#!/usr/bin/env python3
"""
CLI tool to run ingestion with coverage tracking enabled.
"""
import os
import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COVERAGE_DIR = REPO_ROOT / "tools" / "debug" / "coverage" / "coverage_reports"
DEFAULT_COVERAGE_DIR_STR = str(DEFAULT_COVERAGE_DIR)

sys.path.insert(0, str(REPO_ROOT))

from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.ingestion.options import IngestionOptions
from src.conf import settings


def enable_coverage_tracking():
    """Enable coverage tracking in settings."""
    try:
        # Try to enable coverage tracking
        setattr(settings, 'INGESTION_COVERAGE_ENABLED', True)
        print("✓ Coverage tracking enabled")
        return True
    except Exception as e:
        print(f"⚠ Could not enable coverage tracking via settings: {e}")
        print("  You may need to set INGESTION_COVERAGE_ENABLED=True in your .env file")
        return False


def run_ingestion_with_coverage(root_paths, output_dir=None, dry_run=False):
    """
    Run ingestion with coverage tracking enabled.
    
    Args:
        root_paths: List of root paths to ingest
        output_dir: Directory for coverage reports (default: tools/debug/coverage/coverage_reports)
        dry_run: If True, only discover files without ingesting
    """
    # Enable coverage tracking
    if not enable_coverage_tracking():
        print("Proceeding without coverage tracking...")
    
    # Create ingestion options
    options = IngestionOptions(
        root_paths=tuple(root_paths),
        allowed_extensions={'.txt', '.md', '.pdf', '.docx', '.py'},
        excluded_directory_names={'.git', '__pycache__', 'node_modules', 'venv'},
        dry_run=dry_run,
    )
    
    # Create orchestrator
    orchestrator = IngestionOrchestrator()
    
    print(f"Starting ingestion with coverage tracking...")
    print(f"  Root paths: {root_paths}")
    print(f"  Coverage reports will be saved to: {output_dir or DEFAULT_COVERAGE_DIR_STR}")
    print()
    
    # Run ingestion
    try:
        report = orchestrator.run_with_report(options)
        
        print("=" * 60)
        print("INGESTION COMPLETED")
        print("=" * 60)
        
        # Print ingestion summary
        discovery = report.get('discovery', {})
        pipeline = report.get('pipeline', {})
        coverage = report.get('coverage', {})
        
        print(f"\nDiscovery:")
        print(f"  Total files: {discovery.get('total_files', 0)}")
        print(f"  Visited directories: {discovery.get('visited_dirs', 0)}")
        
        print(f"\nPipeline:")
        print(f"  Processed files: {pipeline.get('processed_files', 0)}")
        print(f"  Ingested: {pipeline.get('ingested', 0)}")
        print(f"  Failed: {pipeline.get('failed', 0)}")
        
        # Print coverage summary if available
        if coverage:
            print(f"\nCoverage Analysis:")
            
            if coverage.get('reports_generated'):
                reports = coverage.get('report_paths', {})
                summary = coverage.get('summary', {})
                
                print(f"  Reports generated:")
                for report_type, report_path in reports.items():
                    if os.path.exists(report_path):
                        print(f"    {report_type}: {report_path}")
                
                print(f"\n  Orphaned code summary:")
                print(f"    Total files analyzed: {summary.get('total_files', 0)}")
                print(f"    Orphaned files: {summary.get('orphaned_files', 0)}")
                print(f"    Orphaned lines: {summary.get('orphaned_lines', 0)}")
                
                # Calculate coverage percentage
                total_files = summary.get('total_files', 0)
                orphaned_files = summary.get('orphaned_files', 0)
                if total_files > 0:
                    coverage_percent = ((total_files - orphaned_files) / total_files) * 100
                    print(f"    File coverage: {coverage_percent:.1f}%")
                
                html_report_fallback = DEFAULT_COVERAGE_DIR / "html" / "index.html"
                print(f"\n  To view HTML report: open {reports.get('html_report', str(html_report_fallback))}")
            else:
                print(f"  Coverage reports not generated: {coverage.get('error', 'Unknown error')}")
        else:
            print(f"\nCoverage: Not enabled or no data available")
        
        print(f"\nStatus: {report.get('status', 'unknown')}")
        print(f"Run ID: {report.get('run_id', 'N/A')}")
        
        return 0
        
    except Exception as e:
        print(f"\n✗ Ingestion failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    parser = argparse.ArgumentParser(
        description='Run ingestion with code coverage tracking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s .                          # Ingest current directory
  %(prog)s /path/to/docs              # Ingest specific directory
  %(prog)s dir1 dir2 dir3             # Ingest multiple directories

Coverage reports will be saved to tools/debug/coverage/coverage_reports/
"""
    )
    
    parser.add_argument(
        'paths',
        nargs='+',
        help='Root paths to ingest'
    )
    
    parser.add_argument(
        '--output-dir',
        '-o',
        default=DEFAULT_COVERAGE_DIR_STR,
        help='Directory for coverage reports (default: tools/debug/coverage/coverage_reports)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run (discover files but don\'t ingest)'
    )
    
    args = parser.parse_args()
    
    # Validate paths
    valid_paths = []
    for path in args.paths:
        path_obj = Path(path)
        if not path_obj.exists():
            print(f"Warning: Path does not exist: {path}")
        else:
            valid_paths.append(str(path_obj.absolute()))
    
    if not valid_paths:
        print("Error: No valid paths provided")
        return 1
    
    # Run ingestion with coverage
    return run_ingestion_with_coverage(valid_paths, args.output_dir, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
