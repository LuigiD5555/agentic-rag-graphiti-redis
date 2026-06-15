# Dynamic Code Coverage Tracking for Ingestion Pipeline

## Overview

This system provides dynamic code coverage analysis during actual ingestion pipeline execution. Unlike traditional test coverage, this tracks which lines, functions, and branches of your code are executed during real ingestion workflows, correlating coverage data with specific workflow phases.

## Key Features

1. **Dynamic Execution Tracking**: Monitors code execution during real ingestion, not just tests
2. **Phase Correlation**: Tracks coverage per workflow phase (DISCOVER → EXTRACT → ...)
3. **Orphaned Code Detection**: Identifies code that is never executed during ingestion
4. **Comprehensive Reports**: Generates text, HTML, and JSON reports with phase analysis
5. **Integration Ready**: Seamlessly integrates with existing ingestion orchestrator

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Coverage Tracker                          │
├─────────────────────────────────────────────────────────────┤
│  • Tracks line, function, and branch coverage               │
│  • Correlates coverage with workflow phases                 │
│  • Identifies orphaned code                                 │
│  • Generates comprehensive reports                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                 Ingestion Orchestrator                       │
├─────────────────────────────────────────────────────────────┤
│  • Automatically enables coverage tracking                   │
│  • Integrates coverage into run reports                     │
│  • Provides coverage summary in ingestion results           │
└─────────────────────────────────────────────────────────────┘
```

> **Coverage Toolkit Location:** All coverage tooling, scripts, and generated reports live under `tools/debug/coverage`. Run the CLI via `python tools/debug/coverage/run_ingestion_with_coverage.py` and inspect results in `tools/debug/coverage/coverage_reports`.

## Installation

1. Add `coverage>=7.0.0` to your `requirements.txt`
2. The coverage tracker is automatically available in the ingestion pipeline

## Usage

### Method 1: Using the CLI Tool

```bash
# Run ingestion with coverage tracking
python tools/debug/coverage/run_ingestion_with_coverage.py /path/to/your/documents

# With custom output directory
python tools/debug/coverage/run_ingestion_with_coverage.py /path/to/docs --output-dir ./my_coverage_reports

# Dry run (discover files only)
python tools/debug/coverage/run_ingestion_with_coverage.py . --dry-run
```

### Method 2: Programmatic Usage

```python
from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.ingestion.options import IngestionOptions
from src.conf import settings

# Enable coverage tracking
settings.INGESTION_COVERAGE_ENABLED = True

# Create orchestrator and run ingestion
orchestrator = IngestionOrchestrator()
options = IngestionOptions(
    root_paths=('.',),
    allowed_extensions={'.txt', '.md', '.pdf'},
    excluded_directory_names={'.git', '__pycache__'},
)

report = orchestrator.run_with_report(options)

# Access coverage data
coverage_report = report.get('coverage')
if coverage_report and coverage_report.get('reports_generated'):
    print(f"Coverage reports: {coverage_report['report_paths']}")
    print(f"Orphaned files: {coverage_report['summary']['orphaned_files']}")
```

### Method 3: Manual Coverage Tracking

```python
from src.workflows.ingestion.coverage_tracker import (
    init_global_coverage_tracker,
    start_coverage_tracking,
    stop_coverage_tracking,
    generate_coverage_reports,
    get_orphaned_code_analysis,
    coverage_phase,
    WorkflowPhase,
)

# Initialize tracker
init_global_coverage_tracker(
    source_dirs=['src'],
    output_dir='tools/debug/coverage/coverage_reports'
)

# Start tracking
start_coverage_tracking()

# Track specific phases
with coverage_phase(WorkflowPhase.DISCOVER):
    # Discovery code here
    pass

with coverage_phase(WorkflowPhase.EXTRACT):
    # Extraction code here
    pass

# Stop tracking and generate reports
stop_coverage_tracking()
reports = generate_coverage_reports()

# Analyze orphaned code
orphaned = get_orphaned_code_analysis()
print(f"Orphaned lines: {orphaned['total_orphaned_lines']}")
```

## Workflow Phases

The tracker correlates coverage with these workflow phases:

| Phase | Description |
|-------|-------------|
| `DISCOVER` | File discovery and scanning |
| `PREPROCESS` | File preprocessing and normalization |
| `EXTRACT` | Content extraction and parsing |
| `EMBED` | Embedding generation |
| `STORE` | Vector storage operations |
| `CLEANUP` | Resource cleanup and temporary file removal |
| `ORCHESTRATION` | Overall pipeline orchestration |

## Reports Generated

1. **Text Report** (`coverage_report.txt`): Console-friendly coverage summary
2. **HTML Report** (`html/index.html`): Interactive web report with line-by-line analysis
3. **JSON Analysis** (`coverage_analysis.json`): Detailed phase correlation data
4. **Orphaned Code** (`orphaned_code.json`): List of files and lines never executed

## Configuration

Add to your `.env` file or settings:

```bash
# Enable/disable coverage tracking
INGESTION_COVERAGE_ENABLED=True

# Source directories to track (comma-separated)
INGESTION_COVERAGE_SOURCE_DIRS=src,lib

# Output directory for reports
INGESTION_COVERAGE_OUTPUT_DIR=tools/debug/coverage/coverage_reports
```

## Orphaned Code Analysis

Orphaned code detection helps identify:

1. **Dead functions**: Functions never called during ingestion
2. **Unused imports**: Imported modules never used
3. **Redundant code**: Code paths never executed
4. **Configuration branches**: Feature flags or config options never tested

Example orphaned code report:
```json
{
  "orphaned_files": ["src/utils/old_module.py"],
  "orphaned_lines": {
    "src/workflows/ingestion/legacy.py": [45, 67, 89, 112]
  },
  "total_files": 93,
  "total_orphaned_files": 2,
  "total_orphaned_lines": 156
}
```

## Best Practices

1. **Run coverage during real ingestion**: Use actual document sets, not just test files
2. **Analyze phase coverage**: Identify which phases have low code coverage
3. **Review orphaned code regularly**: Remove or refactor unused code
4. **Compare across runs**: Track coverage improvements over time
5. **Integrate with CI/CD**: Add coverage tracking to your deployment pipeline

## Troubleshooting

### Coverage not enabled
- Check `INGESTION_COVERAGE_ENABLED` is set to `True`
- Verify `coverage` package is installed (`pip install coverage>=7.0.0`)

### No reports generated
- Ensure the ingestion pipeline actually executes code
- Check write permissions for the output directory
- Look for errors in the logs

### Inaccurate coverage
- Coverage tracking starts after `start_coverage_tracking()` is called
- Ensure all source directories are included in `source_dirs`
- Branch coverage requires Python 3.11+ for best results

## Benefits

1. **Identify Bloat**: Find and remove unused code
2. **Debug Pipeline**: See which code paths execute during failures
3. **Optimize Performance**: Focus optimization on frequently executed code
4. **Improve Testing**: Ensure test coverage matches real usage patterns
5. **Document Usage**: Understand how code is actually used in production

## Example Workflow

```bash
# 1. Run ingestion with coverage
python tools/debug/coverage/run_ingestion_with_coverage.py ./documents

# 2. Check coverage summary
cat tools/debug/coverage/coverage_reports/coverage_report.txt

# 3. View detailed HTML report
open tools/debug/coverage/coverage_reports/html/index.html

# 4. Analyze orphaned code
cat tools/debug/coverage/coverage_reports/orphaned_code.json | jq .

# 5. Review phase correlation
cat tools/debug/coverage/coverage_reports/coverage_analysis.json | jq '.phases'
```

## Integration with Existing Tests

The coverage tracker can also be used with your existing test suite:

```bash
# Run tests with coverage tracking
python -m pytest --cov=src --cov-report=html:test_coverage tests/

# Compare test coverage vs ingestion coverage
# This helps identify gaps between tested code and actually used code
```

## Coverage Artifacts

- `tools/debug/coverage/cleanup_bloat.py`: Script that consumes `tools/debug/coverage/coverage_reports/orphaned_code.json` to drive controlled cleanup of legacy code.
- `tools/debug/coverage/code_bloat_analysis.md`: Report that summarizes orphaned code distribution and cleanup recommendations derived from coverage runs.

## Conclusion

This dynamic coverage tracking system provides valuable insights into how your ingestion pipeline actually executes in production. By correlating code execution with workflow phases and identifying orphaned code, you can maintain a lean, efficient codebase and quickly identify issues in your ingestion pipeline.
