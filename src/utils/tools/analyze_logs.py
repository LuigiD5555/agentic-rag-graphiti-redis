#!/usr/bin/env python3
"""
Log Analysis Tool for RAG Tools

Analyzes systemd journal logs to detect error patterns, anomalies, and trends.

Usage:
    python -m src.utils.tools.analyze_logs [--tool TOOL] [--since TIMESPEC] [--format FORMAT]

Examples:
    python -m src.utils.tools.analyze_logs --tool office --since "24 hours ago"
    python -m src.utils.tools.analyze_logs --all --since "1 week ago" --format json
"""

import subprocess
import sys
import re
import argparse
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple
import json


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


class LogAnalyzer:
    """Analyzes systemd journal logs for error patterns."""

    TOOLS = ['office', 'archive', 'ocr', 'gpu']

    # Error patterns to detect
    ERROR_PATTERNS = [
        (r'(?i)error', 'Generic Error'),
        (r'(?i)exception', 'Exception'),
        (r'(?i)failed', 'Failure'),
        (r'(?i)timeout', 'Timeout'),
        (r'(?i)connection refused', 'Connection Refused'),
        (r'(?i)permission denied', 'Permission Denied'),
        (r'(?i)out of memory', 'Out of Memory'),
        (r'(?i)disk (?:full|space)', 'Disk Space'),
        (r'HTTP/1\.1" 5\d\d', 'HTTP 5xx Error'),
        (r'HTTP/1\.1" 4\d\d', 'HTTP 4xx Error'),
        (r'(?i)traceback', 'Python Traceback'),
    ]

    def __init__(self, tools: List[str] = None, since: str = '24 hours ago'):
        """
        Initialize analyzer.

        Args:
            tools: List of tools to analyze (default: all)
            since: Time range for analysis
        """
        self.tools = tools if tools else self.TOOLS
        self.since = since
        self.project_root = Path(__file__).parent.parent.parent.parent

    def get_logs(self, tool: str) -> str:
        """
        Fetch logs for a specific tool.

        Args:
            tool: Tool name

        Returns:
            Log output as string
        """
        try:
            result = subprocess.run(
                ['journalctl', '--user', '-u', f'tool-{tool}.service',
                 '--since', self.since, '--no-pager', '-o', 'cat'],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout
        except Exception as e:
            print(f"{Colors.RED}Failed to get logs for {tool}:{Colors.NC} {e}", file=sys.stderr)
            return ''

    def count_log_lines(self, tool: str) -> int:
        """
        Count total log lines for a tool.

        Args:
            tool: Tool name

        Returns:
            Number of log lines
        """
        logs = self.get_logs(tool)
        return len(logs.splitlines()) if logs else 0

    def find_errors(self, tool: str) -> Dict[str, List[str]]:
        """
        Find error patterns in logs.

        Args:
            tool: Tool name

        Returns:
            Dictionary mapping error categories to matching lines
        """
        logs = self.get_logs(tool)
        errors = defaultdict(list)

        for line in logs.splitlines():
            for pattern, category in self.ERROR_PATTERNS:
                if re.search(pattern, line):
                    errors[category].append(line)

        return dict(errors)

    def count_http_status(self, tool: str) -> Counter:
        """
        Count HTTP status codes in logs.

        Args:
            tool: Tool name

        Returns:
            Counter of HTTP status codes
        """
        logs = self.get_logs(tool)
        status_codes = Counter()

        for line in logs.splitlines():
            # Match patterns like: "POST /convert HTTP/1.1" 200 OK
            match = re.search(r'HTTP/1\.1"\s+(\d{3})', line)
            if match:
                status_codes[match.group(1)] += 1

        return status_codes

    def detect_anomalies(self, tool: str) -> List[str]:
        """
        Detect anomalies in logs.

        Args:
            tool: Tool name

        Returns:
            List of anomaly descriptions
        """
        anomalies = []
        errors = self.find_errors(tool)
        http_status = self.count_http_status(tool)

        # Check for high error rates
        total_errors = sum(len(lines) for lines in errors.values())
        if total_errors > 100:
            anomalies.append(f"High error count: {total_errors} errors found")

        # Check for HTTP errors
        http_errors = sum(count for code, count in http_status.items() if code.startswith(('4', '5')))
        http_total = sum(http_status.values())
        if http_total > 0 and http_errors / http_total > 0.1:
            error_rate = (http_errors / http_total) * 100
            anomalies.append(f"High HTTP error rate: {error_rate:.1f}% ({http_errors}/{http_total})")

        # Check for specific critical errors
        if 'Out of Memory' in errors:
            anomalies.append("Critical: Out of Memory errors detected")

        if 'Permission Denied' in errors:
            anomalies.append("Critical: Permission Denied errors detected")

        return anomalies

    def analyze_tool(self, tool: str) -> Dict:
        """
        Comprehensive analysis of a single tool.

        Args:
            tool: Tool name

        Returns:
            Dictionary with analysis results
        """
        return {
            'tool': tool,
            'total_lines': self.count_log_lines(tool),
            'errors': self.find_errors(tool),
            'http_status': dict(self.count_http_status(tool)),
            'anomalies': self.detect_anomalies(tool)
        }

    def analyze_all(self) -> Dict[str, Dict]:
        """
        Analyze all configured tools.

        Returns:
            Dictionary mapping tool names to analysis results
        """
        results = {}
        for tool in self.tools:
            results[tool] = self.analyze_tool(tool)
        return results

    def print_summary(self, results: Dict[str, Dict]):
        """
        Print human-readable summary of analysis.

        Args:
            results: Analysis results from analyze_all()
        """
        print(f"\n{Colors.BLUE}{'='*70}{Colors.NC}")
        print(f"{Colors.BOLD}Log Analysis Summary{Colors.NC}")
        print(f"{Colors.CYAN}Time range:{Colors.NC} {self.since}")
        print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        for tool, data in results.items():
            print(f"{Colors.BOLD}{tool.upper()}{Colors.NC}")
            print(f"  Total log lines: {data['total_lines']}")

            # HTTP Status codes
            if data['http_status']:
                print(f"\n  {Colors.CYAN}HTTP Status Codes:{Colors.NC}")
                for code in sorted(data['http_status'].keys()):
                    count = data['http_status'][code]
                    color = Colors.GREEN if code.startswith('2') else (
                        Colors.YELLOW if code.startswith('3') else Colors.RED
                    )
                    print(f"    {color}{code}{Colors.NC}: {count}")

            # Errors
            if data['errors']:
                print(f"\n  {Colors.YELLOW}Error Patterns:{Colors.NC}")
                for category, lines in sorted(data['errors'].items(), key=lambda x: -len(x[1])):
                    print(f"    {Colors.RED}●{Colors.NC} {category}: {len(lines)} occurrences")
                    if len(lines) <= 3:
                        for line in lines:
                            print(f"      {line[:100]}")

            # Anomalies
            if data['anomalies']:
                print(f"\n  {Colors.MAGENTA}⚠ Anomalies:{Colors.NC}")
                for anomaly in data['anomalies']:
                    print(f"    {Colors.RED}!{Colors.NC} {anomaly}")

            print()

        # Overall summary
        total_errors = sum(
            sum(len(lines) for lines in data['errors'].values())
            for data in results.values()
        )

        print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
        print(f"{Colors.BOLD}Overall Statistics{Colors.NC}")
        print(f"  Total errors across all tools: {total_errors}")

        tools_with_anomalies = [
            tool for tool, data in results.items()
            if data['anomalies']
        ]

        if tools_with_anomalies:
            print(f"  {Colors.RED}Tools with anomalies:{Colors.NC} {', '.join(tools_with_anomalies)}")
        else:
            print(f"  {Colors.GREEN}No anomalies detected{Colors.NC}")

        print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

    def export_json(self, results: Dict[str, Dict], output_file: Path = None):
        """
        Export results as JSON.

        Args:
            results: Analysis results
            output_file: Optional output file path
        """
        if output_file is None:
            output_file = self.project_root / 'logs' / 'analysis' / f'log_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Add metadata
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'time_range': self.since,
            'tools': self.tools,
            'results': results
        }

        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)

        print(f"{Colors.GREEN}Analysis exported to:{Colors.NC} {output_file}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze RAG tool logs for error patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze last 24 hours for all tools
  python -m src.utils.tools.analyze_logs

  # Analyze specific tool for last week
  python -m src.utils.tools.analyze_logs --tool office --since "1 week ago"

  # Export results as JSON
  python -m src.utils.tools.analyze_logs --format json --output results.json

  # Analyze all tools since yesterday
  python -m src.utils.tools.analyze_logs --all --since yesterday
        """
    )

    parser.add_argument(
        '--tool',
        type=str,
        choices=['office', 'archive', 'ocr', 'gpu'],
        help='Specific tool to analyze'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all tools'
    )

    parser.add_argument(
        '--since',
        type=str,
        default='24 hours ago',
        help='Time range for analysis (default: "24 hours ago")'
    )

    parser.add_argument(
        '--format',
        type=str,
        choices=['text', 'json'],
        default='text',
        help='Output format (default: text)'
    )

    parser.add_argument(
        '--output',
        type=str,
        help='Output file for JSON format'
    )

    args = parser.parse_args()

    # Determine which tools to analyze
    if args.tool:
        tools = [args.tool]
    elif args.all:
        tools = None  # Analyze all
    else:
        tools = None  # Default to all

    # Create analyzer
    analyzer = LogAnalyzer(tools=tools, since=args.since)

    # Run analysis
    results = analyzer.analyze_all()

    # Output results
    if args.format == 'json':
        output_file = Path(args.output) if args.output else None
        analyzer.export_json(results, output_file)
    else:
        analyzer.print_summary(results)

    sys.exit(0)


if __name__ == '__main__':
    main()
