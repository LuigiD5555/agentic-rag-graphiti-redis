#!/usr/bin/env python3
"""
Real-time Code Usage Monitor

Monitors code execution across different pipelines (ingestion, queries, processing)
and identifies unused code snippets with detailed context.
"""

import os
import sys
import json
import csv
import ast
import time
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple
import logging
import coverage

logger = logging.getLogger(__name__)


class CodeSnippetExtractor:
    """Extracts code snippets from source files with context."""
    
    def __init__(self):
        self.snippet_cache = {}
    
    def extract_snippet(self, file_path: str, line_start: int, line_end: int) -> str:
        """Extract code snippet from file with line numbers."""
        cache_key = f"{file_path}:{line_start}:{line_end}"
        if cache_key in self.snippet_cache:
            return self.snippet_cache[cache_key]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Adjust line numbers to 0-based indexing
            start_idx = max(0, line_start - 1)
            end_idx = min(len(lines), line_end)
            
            snippet_lines = lines[start_idx:end_idx]
            
            # Add line numbers
            snippet = ""
            for i, line in enumerate(snippet_lines, start=start_idx + 1):
                snippet += f"{i:4d}: {line}"
            
            self.snippet_cache[cache_key] = snippet
            return snippet
            
        except Exception as e:
            logger.error(f"Failed to extract snippet from {file_path}: {e}")
            return f"Error extracting snippet from {file_path} (lines {line_start}-{line_end})"
    
    def get_ast_info(self, file_path: str, line_number: int) -> Dict[str, Any]:
        """Get AST information for a specific line."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if hasattr(node, 'lineno') and node.lineno == line_number:
                    node_type = type(node).__name__
                    
                    # Get additional context based on node type
                    context = {
                        "node_type": node_type,
                        "name": self._get_node_name(node),
                        "parent_type": self._get_parent_type(tree, node),
                        "scope": self._get_scope(tree, node)
                    }
                    
                    return context
            
            return {"node_type": "unknown", "name": "", "parent_type": "", "scope": ""}
            
        except Exception as e:
            logger.error(f"Failed to parse AST for {file_path}: {e}")
            return {"node_type": "error", "name": "", "parent_type": "", "scope": ""}
    
    def _get_node_name(self, node) -> str:
        """Get name of AST node."""
        if hasattr(node, 'name'):
            return node.name
        elif hasattr(node, 'id'):
            return node.id
        elif hasattr(node, 'attr'):
            return node.attr
        elif isinstance(node, ast.FunctionDef):
            return node.name
        elif isinstance(node, ast.ClassDef):
            return node.name
        elif isinstance(node, ast.Assign):
            if len(node.targets) > 0 and hasattr(node.targets[0], 'id'):
                return node.targets[0].id
        return ""
    
    def _get_parent_type(self, tree, node) -> str:
        """Get parent node type."""
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    return type(parent).__name__
        return ""
    
    def _get_scope(self, tree, node) -> str:
        """Get scope information."""
        scope = []
        current = node
        
        while True:
            parent = None
            for parent_node in ast.walk(tree):
                for child in ast.iter_child_nodes(parent_node):
                    if child is current:
                        parent = parent_node
                        break
                if parent:
                    break
            
            if not parent:
                break
            
            if isinstance(parent, ast.FunctionDef):
                scope.insert(0, f"function:{parent.name}")
            elif isinstance(parent, ast.ClassDef):
                scope.insert(0, f"class:{parent.name}")
            elif isinstance(parent, ast.Module):
                scope.insert(0, "module")
                break
            
            current = parent
        
        return " -> ".join(scope)


class PipelineClassifier:
    """Classifies code snippets by pipeline/context."""
    
    def __init__(self):
        self.pipeline_patterns = {
            "ingestion": [
                "src/ingestion/",
                "src/workflows/ingestion/",
                "ingest", "scanner", "spool", "ledger",
                "document-processor", "extractor", "ocr"
            ],
            "web_queries": [
                "src/apps/websearch/",
                "src/api/routes/search",
                "websearch", "searxng", "search"
            ],
            "rag_queries": [
                "src/query/",
                "src/workflows/query/",
                "src/api/routes/query",
                "rag", "retrieval", "embedding"
            ],
            "file_processing": [
                "src/utils/file_operations",
                "tools/document-processor/",
                "tools/extractor/",
                "conversion", "parser", "processor"
            ],
            "messaging": [
                "src/messaging/",
                "rabbitmq", "broker", "producer", "consumer"
            ],
            "storage": [
                "src/backends/storage/",
                "weaviate", "neo4j", "sqlite", "vector"
            ],
            "llm": [
                "src/backends/llm/",
                "src/api/models",
                "llm", "openai", "ollama", "lmstudio"
            ],
            "monitoring": [
                "src/monitoring/",
                "tools/monitoring/",
                "monitor", "dashboard", "health"
            ]
        }
    
    def classify_file(self, file_path: str) -> List[str]:
        """Classify a file into one or more pipelines."""
        pipelines = set()
        
        for pipeline_name, patterns in self.pipeline_patterns.items():
            for pattern in patterns:
                if pattern in file_path.lower():
                    pipelines.add(pipeline_name)
        
        # If no specific pipeline found, try to infer from directory structure
        if not pipelines:
            if "ingestion" in file_path.lower():
                pipelines.add("ingestion")
            elif "query" in file_path.lower():
                pipelines.add("rag_queries")
            elif "api" in file_path.lower():
                pipelines.add("rag_queries")  # API is often query-related
            elif "utils" in file_path.lower():
                pipelines.add("file_processing")  # Utils often used in processing
        
        return list(pipelines) if pipelines else ["general"]


class RealTimeCoverageMonitor:
    """Real-time coverage monitoring across pipelines."""
    
    def __init__(self, source_dir: str = "src", output_dir: str = "/app/reports/realtime"):
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.coverage = coverage.Coverage(
            source=[str(self.source_dir)],
            branch=True,
            data_file=str(self.output_dir / ".coverage")
        )
        self.snippet_extractor = CodeSnippetExtractor()
        self.pipeline_classifier = PipelineClassifier()
        self.monitoring = False
        self.monitor_thread = None
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def start_monitoring(self):
        """Start real-time coverage monitoring."""
        if self.monitoring:
            logger.warning("Monitoring already started")
            return
        
        logger.info("Starting real-time coverage monitoring...")
        self.coverage.start()
        self.monitoring = True
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            name="realtime-monitor",
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("Real-time monitoring started")
    
    def stop_monitoring(self):
        """Stop real-time coverage monitoring."""
        if not self.monitoring:
            logger.warning("Monitoring not started")
            return
        
        logger.info("Stopping real-time coverage monitoring...")
        self.monitoring = False
        self.coverage.stop()
        self.coverage.save()
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("Real-time monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring:
            try:
                # Save coverage data periodically
                self.coverage.save()
                time.sleep(60)  # Save every minute
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(10)
    
    def analyze_unused_code(self) -> List[Dict[str, Any]]:
        """Analyze and identify unused code with detailed context."""
        if self.monitoring:
            self.coverage.stop()
            self.coverage.save()
        
        # Get coverage data
        self.coverage.load()
        data = self.coverage.get_data()
        
        unused_snippets = []
        
        # Analyze each file
        for filename in data.measured_files():
            if not filename.startswith(str(self.source_dir)):
                continue
            
            # Get lines not executed
            lines = data.lines(filename)
            if not lines:
                continue
            
            # Read file to get total lines
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    total_lines = len(f.readlines())
            except:
                continue
            
            # Find unused lines
            unused_lines = set(range(1, total_lines + 1)) - set(lines)
            
            if not unused_lines:
                continue
            
            # Group consecutive unused lines into blocks
            blocks = self._group_consecutive_lines(sorted(unused_lines))
            
            # Analyze each block
            for start_line, end_line in blocks:
                snippet_info = self._analyze_snippet(
                    filename, start_line, end_line
                )
                
                if snippet_info:
                    unused_snippets.append(snippet_info)
        
        # Restart monitoring if it was running
        if self.monitoring:
            self.coverage.start()
        
        return unused_snippets
    
    def _group_consecutive_lines(self, lines: List[int]) -> List[Tuple[int, int]]:
        """Group consecutive line numbers into blocks."""
        if not lines:
            return []
        
        blocks = []
        start = lines[0]
        end = lines[0]
        
        for line in lines[1:]:
            if line == end + 1:
                end = line
            else:
                blocks.append((start, end))
                start = line
                end = line
        
        blocks.append((start, end))
        return blocks
    
    def _analyze_snippet(self, file_path: str, start_line: int, end_line: int) -> Optional[Dict[str, Any]]:
        """Analyze a specific code snippet."""
        try:
            # Extract snippet
            snippet = self.snippet_extractor.extract_snippet(file_path, start_line, end_line)
            
            # Get AST information for the first line
            ast_info = self.snippet_extractor.get_ast_info(file_path, start_line)
            
            # Classify by pipeline
            pipelines = self.pipeline_classifier.classify_file(file_path)
            
            # Determine snippet status
            status = self._determine_snippet_status(ast_info, snippet)
            
            # Determine object type
            object_type = self._determine_object_type(ast_info)
            
            snippet_info = {
                "file": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "snippet": snippet,
                "status": status,
                "object_type": object_type,
                "pipelines": pipelines,
                "ast_info": ast_info,
                "timestamp": datetime.now().isoformat()
            }
            
            return snippet_info
            
        except Exception as e:
            logger.error(f"Failed to analyze snippet {file_path}:{start_line}-{end_line}: {e}")
            return None
    
    def _determine_snippet_status(self, ast_info: Dict[str, Any], snippet: str) -> str:
        """Determine the status of a code snippet."""
        node_type = ast_info.get("node_type", "")
        
        if node_type in ["FunctionDef", "AsyncFunctionDef"]:
            return "orphaned_function"
        elif node_type == "ClassDef":
            return "orphaned_class"
        elif node_type == "Import" or node_type == "ImportFrom":
            return "unused_import"
        elif node_type == "Assign":
            return "unused_variable"
        elif "test" in snippet.lower():
            return "untested_code"
        else:
            return "unused_code"
    
    def _determine_object_type(self, ast_info: Dict[str, Any]) -> str:
        """Determine the type of object."""
        node_type = ast_info.get("node_type", "")
        
        type_mapping = {
            "FunctionDef": "function",
            "AsyncFunctionDef": "async_function",
            "ClassDef": "class",
            "Assign": "variable",
            "Import": "import",
            "ImportFrom": "import",
            "Expr": "expression",
            "Return": "return_statement",
            "If": "conditional",
            "For": "loop",
            "While": "loop",
            "Try": "exception_handler",
            "With": "context_manager"
        }
        
        return type_mapping.get(node_type, "unknown")


class ReportGenerator:
    """Generates detailed reports of unused code."""
    
    def __init__(self, output_dir: str = "/app/reports/realtime"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_csv_report(self, snippets: List[Dict[str, Any]], filename: str = None) -> str:
        """Generate CSV report."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"unused_code_{timestamp}.csv"
        
        filepath = self.output_dir / filename
        
        fieldnames = [
            "file", "start_line", "end_line", "status", "object_type",
            "pipelines", "node_type", "name", "parent_type", "scope",
            "timestamp"
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for snippet in snippets:
                row = {
                    "file": snippet["file"],
                    "start_line": snippet["start_line"],
                    "end_line": snippet["end_line"],
                    "status": snippet["status"],
                    "object_type": snippet["object_type"],
                    "pipelines": ";".join(snippet["pipelines"]),
                    "node_type": snippet["ast_info"].get("node_type", ""),
                    "name": snippet["ast_info"].get("name", ""),
                    "parent_type": snippet["ast_info"].get("parent_type", ""),
                    "scope": snippet["ast_info"].get("scope", ""),
                    "timestamp": snippet["timestamp"]
                }
                writer.writerow(row)
        
        logger.info(f"CSV report generated: {filepath}")
        return str(filepath)
    
    def generate_markdown_report(self, snippets: List[Dict[str, Any]], filename: str = None) -> str:
        """Generate Markdown report with code snippets."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"unused_code_{timestamp}.md"
        
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# Unused Code Analysis Report\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"Total snippets found: {len(snippets)}\n\n")
            
            # Summary table
            f.write("## Summary\n\n")
            f.write("| Status | Count |\n")
            f.write("|--------|-------|\n")
            
            status_counts = {}
            for snippet in snippets:
                status = snippet["status"]
                status_counts[status] = status_counts.get(status, 0) + 1
            
            for status, count in sorted(status_counts.items()):
                f.write(f"| {status} | {count} |\n")
            
            f.write("\n## Detailed Analysis\n\n")
            
            # Detailed analysis for each snippet
            for i, snippet in enumerate(snippets, 1):
                f.write(f"### Snippet {i}: {snippet['file']}:{snippet['start_line']}-{snippet['end_line']}\n\n")
                
                f.write("**Metadata:**\n")
                f.write(f"- Status: `{snippet['status']}`\n")
                f.write(f"- Object Type: `{snippet['object_type']}`\n")
                f.write(f"- Pipelines: `{', '.join(snippet['pipelines'])}`\n")
                f.write(f"- AST Node: `{snippet['ast_info'].get('node_type', 'unknown')}`\n")
                f.write(f"- Name: `{snippet['ast_info'].get('name', '')}`\n")
                f.write(f"- Scope: `{snippet['ast_info'].get('scope', '')}`\n\n")
                
                f.write("**Code Snippet:**\n")
                f.write("```python\n")
                f.write(snippet["snippet"])
                f.write("\n```\n\n")
            
            f.write("\n---\n")
            f.write("*Report generated by Real-time Code Usage Monitor*\n")
        
        logger.info(f"Markdown report generated: {filepath}")
        return str(filepath)
    
    def generate_text_report(self, snippets: List[Dict[str, Any]], filename: str = None) -> str:
        """Generate simple text report."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"unused_code_{timestamp}.txt"
        
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("UNUSED CODE ANALYSIS REPORT\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total snippets found: {len(snippets)}\n\n")
            
            for i, snippet in enumerate(snippets, 1):
                f.write(f"\n{'='*60}\n")
                f.write(f"SNIPPET {i}: {snippet['file']}:{snippet['start_line']}-{snippet['end_line']}\n")
                f.write(f"{'='*60}\n\n")
                
                f.write(f"Status: {snippet['status']}\n")
                f.write(f"Object Type: {snippet['object_type']}\n")
                f.write(f"Pipelines: {', '.join(snippet['pipelines'])}\n")
                f.write(f"AST Node: {snippet['ast_info'].get('node_type', 'unknown')}\n")
                f.write(f"Name: {snippet['ast_info'].get('name', '')}\n")
                f.write(f"Scope: {snippet['ast_info'].get('scope', '')}\n\n")
                
                f.write("Code Snippet:\n")
                f.write("-" * 40 + "\n")
                f.write(snippet["snippet"])
                f.write("\n" + "-" * 40 + "\n")
        
        logger.info(f"Text report generated: {filepath}")
        return str(filepath)


class RealTimeMonitoringCLI:
    """Command-line interface for real-time monitoring."""
    
    def __init__(self):
        self.monitor = RealTimeCoverageMonitor()
        self.report_generator = ReportGenerator()
    
    def start(self):
        """Start real-time monitoring."""
        self.monitor.start_monitoring()
        print("Real-time monitoring started. Press Ctrl+C to stop.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop real-time monitoring and generate report."""
        print("\nStopping monitoring...")
        self.monitor.stop_monitoring()
        
        print("Analyzing unused code...")
        snippets = self.monitor.analyze_unused_code()
        
        if snippets:
            print(f"Found {len(snippets)} unused code snippets.")
            
            # Generate reports
            csv_report = self.report_generator.generate_csv_report(snippets)
            md_report = self.report_generator.generate_markdown_report(snippets)
            txt_report = self.report_generator.generate_text_report(snippets)
            
            print(f"\nReports generated:")
            print(f"  - CSV: {csv_report}")
            print(f"  - Markdown: {md_report}")
            print(f"  - Text: {txt_report}")
        else:
            print("No unused code found.")
    
    def analyze_now(self):
        """Analyze current coverage without stopping monitoring."""
        print("Analyzing current coverage...")
        snippets = self.monitor.analyze_unused_code()
        
        if snippets:
            print(f"Found {len(snippets)} unused code snippets.")
            
            # Generate reports
            csv_report = self.report_generator.generate_csv_report(snippets)
            md_report = self.report_generator.generate_markdown_report(snippets)
            
            print(f"\nReports generated:")
            print(f"  - CSV: {csv_report}")
            print(f"  - Markdown: {md_report}")
        else:
            print("No unused code found.")


def main():
    """Main entry point."""
    import argparse
    
    # Check if real-time monitoring is enabled via environment variable
    if os.getenv("ENABLE_REALTIME_MONITORING", "false").lower() != "true":
        print("Real-time monitoring is disabled. Set ENABLE_REALTIME_MONITORING=true to enable.")
        print("This feature is only available in development mode.")
        sys.exit(0)
    
    parser = argparse.ArgumentParser(description="Real-time Code Usage Monitor")
    parser.add_argument("command", choices=["start", "stop", "analyze", "report"],
                       help="Command to execute")
    parser.add_argument("--format", choices=["csv", "md", "txt", "all"],
                       default="all", help="Report format")
    
    args = parser.parse_args()
    
    cli = RealTimeMonitoringCLI()
    
    if args.command == "start":
        cli.start()
    elif args.command == "stop":
        cli.stop()
    elif args.command == "analyze":
        cli.analyze_now()
    elif args.command == "report":
        # Generate report from existing data
        monitor = RealTimeCoverageMonitor()
        snippets = monitor.analyze_unused_code()
        
        if snippets:
            report_gen = ReportGenerator()
            
            if args.format == "csv" or args.format == "all":
                csv_report = report_gen.generate_csv_report(snippets)
                print(f"CSV report: {csv_report}")
            
            if args.format == "md" or args.format == "all":
                md_report = report_gen.generate_markdown_report(snippets)
                print(f"Markdown report: {md_report}")
            
            if args.format == "txt" or args.format == "all":
                txt_report = report_gen.generate_text_report(snippets)
                print(f"Text report: {txt_report}")
        else:
            print("No unused code found.")


if __name__ == "__main__":
    main()
