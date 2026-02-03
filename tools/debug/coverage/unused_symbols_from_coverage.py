#!/usr/bin/env python3
"""
unused_symbols_from_coverage.py

Generate a function/method/class "unused" report by crossing:
- Coverage JSON (executed vs missing lines)
- Python AST (symbol boundaries for defs/classes)

This is designed to answer: "Which functions/methods/classes were not executed
during my E2E run?" It does NOT prove they are dead forever—only for that run.

Output formats:
- Markdown report (default)
- CSV report with detailed information including code snippets
"""

from __future__ import annotations  # NOT USED per user preference (kept out intentionally)


import argparse
import ast
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class SymbolSpan:
    """A code symbol (function/method/class) with file span and qualified name."""
    file_path: Path
    qualified_name: str
    kind: str  # "function" | "method" | "class"
    start_line: int
    end_line: int
    decorators: Tuple[str, ...]
    is_async: bool
    is_dunder: bool


@dataclass(frozen=True)
class CoverageFileData:
    """Coverage data for a single file from coverage JSON."""
    file_path: Path
    executed_lines: Set[int]
    missing_lines: Set[int]


@dataclass(frozen=True)
class SymbolCoverageResult:
    """Coverage result for a given symbol."""
    symbol: SymbolSpan
    executed_in_range: int
    total_lines_in_range: int
    coverage_ratio: float
    status: str  # "unused" | "touched"
    notes: Tuple[str, ...]


class CoverageJsonLoader:
    """Load coverage JSON exported by `coverage json -o coverage.json`."""

    def __init__(self, coverage_json_path: Path, repo_root: Path):
        """
        Initialize loader.

        Args:
            coverage_json_path: Path to coverage.json file.
            repo_root: Repository root to normalize paths.
        """
        self.coverage_json_path = coverage_json_path
        self.repo_root = repo_root.resolve()

    def load(self) -> Dict[Path, CoverageFileData]:
        """
        Load coverage.json and return a mapping from absolute file paths to coverage data.

        Returns:
            Mapping: file_path -> CoverageFileData

        Raises:
            FileNotFoundError: If coverage JSON does not exist.
            ValueError: If JSON format is not recognized.
        """
        if not self.coverage_json_path.exists():
            raise FileNotFoundError(f"coverage JSON not found: {self.coverage_json_path}")

        raw = json.loads(self.coverage_json_path.read_text(encoding="utf-8"))
        files = raw.get("files")
        if not isinstance(files, dict):
            raise ValueError("coverage JSON does not contain a 'files' dictionary")

        results: Dict[Path, CoverageFileData] = {}
        for file_name, payload in files.items():
            file_path = self._normalize_file_path(file_name)
            executed = set(payload.get("executed_lines") or [])
            missing = set(payload.get("missing_lines") or [])
            results[file_path] = CoverageFileData(
                file_path=file_path,
                executed_lines=executed,
                missing_lines=missing,
            )
        return results

    def _normalize_file_path(self, file_name: str) -> Path:
        """
        Normalize file paths from coverage output to absolute paths under repo_root when possible.

        Args:
            file_name: Path string in coverage JSON.

        Returns:
            Absolute Path if resolvable; otherwise a resolved Path.
        """
        p = Path(file_name)
        if p.is_absolute():
            return p.resolve()

        # If relative, anchor to repo_root.
        candidate = (self.repo_root / p).resolve()
        return candidate


class PythonSymbolExtractor(ast.NodeVisitor):
    """Extract class/function symbols and their approximate source spans from Python AST."""

    def __init__(self, file_path: Path):
        """
        Initialize extractor.

        Args:
            file_path: The file being parsed.
        """
        self.file_path = file_path
        self._scope_stack: List[str] = []
        self.symbols: List[SymbolSpan] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = self._qualified_name(node.name)
        decorators = tuple(self._decorator_names(node.decorator_list))
        start, end = self._node_span(node)

        self.symbols.append(
            SymbolSpan(
                file_path=self.file_path,
                qualified_name=qualified,
                kind="class",
                start_line=start,
                end_line=end,
                decorators=decorators,
                is_async=False,
                is_dunder=self._is_dunder_name(node.name),
            )
        )

        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function_like(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function_like(node, is_async=True)
        self.generic_visit(node)

    def _record_function_like(self, node: ast.AST, is_async: bool) -> None:
        name = getattr(node, "name", "<unknown>")
        qualified = self._qualified_name(name)
        decorators = tuple(self._decorator_names(getattr(node, "decorator_list", [])))
        start, end = self._node_span(node)

        kind = "method" if self._scope_stack else "function"
        self.symbols.append(
            SymbolSpan(
                file_path=self.file_path,
                qualified_name=qualified,
                kind=kind,
                start_line=start,
                end_line=end,
                decorators=decorators,
                is_async=is_async,
                is_dunder=self._is_dunder_name(name),
            )
        )

    def _qualified_name(self, local_name: str) -> str:
        if not self._scope_stack:
            return local_name
        return ".".join(self._scope_stack + [local_name])

    def _node_span(self, node: ast.AST) -> Tuple[int, int]:
        """
        Get approximate start/end line span for a node.

        Uses `lineno` and (if available) `end_lineno`. Falls back to lineno if missing.

        Args:
            node: AST node.

        Returns:
            (start_line, end_line)
        """
        start = int(getattr(node, "lineno", 1))
        end = int(getattr(node, "end_lineno", start))
        if end < start:
            end = start
        return start, end

    def _decorator_names(self, decorator_list: Sequence[ast.AST]) -> List[str]:
        names: List[str] = []
        for dec in decorator_list:
            names.append(self._expr_to_name(dec))
        return names

    def _expr_to_name(self, expr: ast.AST) -> str:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            return f"{self._expr_to_name(expr.value)}.{expr.attr}"
        if isinstance(expr, ast.Call):
            return self._expr_to_name(expr.func)
        return expr.__class__.__name__

    def _is_dunder_name(self, name: str) -> bool:
        return name.startswith("__") and name.endswith("__")


class RepoWalker:
    """Walk a repository and yield Python files, respecting exclude rules."""

    def __init__(self, repo_root: Path, exclude_dirs: Optional[Sequence[str]] = None):
        """
        Initialize walker.

        Args:
            repo_root: Root of repository.
            exclude_dirs: Directory names to skip.
        """
        self.repo_root = repo_root.resolve()
        self.exclude_dirs = set(exclude_dirs or [])

    def iter_python_files(self) -> Iterable[Path]:
        """
        Iterate Python files under repo_root.

        Yields:
            Absolute paths to .py files.
        """
        for path in self.repo_root.rglob("*.py"):
            if self._is_excluded(path):
                continue
            yield path.resolve()

    def _is_excluded(self, path: Path) -> bool:
        parts = set(path.parts)
        return any(ex in parts for ex in self.exclude_dirs)


class SymbolCoverageAnalyzer:
    """Cross coverage line execution data with AST symbol spans."""

    def __init__(self, repo_root: Path, coverage_by_file: Dict[Path, CoverageFileData]):
        """
        Initialize analyzer.

        Args:
            repo_root: Repository root.
            coverage_by_file: Mapping from file path to coverage line sets.
        """
        self.repo_root = repo_root.resolve()
        self.coverage_by_file = coverage_by_file

    def analyze(self, symbols: Sequence[SymbolSpan]) -> List[SymbolCoverageResult]:
        """
        Analyze coverage for each symbol.

        Args:
            symbols: Extracted symbols.

        Returns:
            List of SymbolCoverageResult.
        """
        results: List[SymbolCoverageResult] = []
        for sym in symbols:
            cov = self.coverage_by_file.get(sym.file_path)
            if cov is None:
                # If the file was not present in coverage output, treat as fully unused.
                results.append(self._result_no_coverage(sym))
                continue

            all_lines = set(range(sym.start_line, sym.end_line + 1))
            executed = cov.executed_lines.intersection(all_lines)
            total = len(all_lines)
            executed_count = len(executed)
            ratio = (executed_count / total) if total > 0 else 0.0

            status = "unused" if executed_count == 0 else "touched"
            notes = self._notes_for_symbol(sym, status, cov)

            results.append(
                SymbolCoverageResult(
                    symbol=sym,
                    executed_in_range=executed_count,
                    total_lines_in_range=total,
                    coverage_ratio=ratio,
                    status=status,
                    notes=tuple(notes),
                )
            )
        return results

    def _result_no_coverage(self, sym: SymbolSpan) -> SymbolCoverageResult:
        notes = ["file-not-in-coverage-json"]
        return SymbolCoverageResult(
            symbol=sym,
            executed_in_range=0,
            total_lines_in_range=max(1, sym.end_line - sym.start_line + 1),
            coverage_ratio=0.0,
            status="unused",
            notes=tuple(notes),
        )

    def _notes_for_symbol(self, sym: SymbolSpan, status: str, cov: CoverageFileData) -> List[str]:
        notes: List[str] = []
        if sym.is_dunder:
            notes.append("dunder")
        if "property" in sym.decorators:
            notes.append("property")
        if "abstractmethod" in sym.decorators or "abc.abstractmethod" in sym.decorators:
            notes.append("abstractmethod")
        if status == "unused" and sym.kind == "class":
            notes.append("class-not-instantiated-or-not-executed")
        if status == "unused" and sym.kind in {"function", "method"}:
            notes.append("function-or-method-not-executed")
        return notes


class MarkdownReporter:
    """Render analysis results into a Markdown report."""

    def __init__(self, repo_root: Path):
        """
        Initialize reporter.

        Args:
            repo_root: Repository root to make paths relative.
        """
        self.repo_root = repo_root.resolve()

    def render(self, results: Sequence[SymbolCoverageResult]) -> str:
        """
        Render a Markdown document.

        Args:
            results: Analysis results.

        Returns:
            Markdown string.
        """
        unused = [r for r in results if r.status == "unused"]
        touched = [r for r in results if r.status == "touched"]

        lines: List[str] = []
        lines.append("# Unused symbols report (coverage × AST)\n")
        lines.append("This report lists functions/methods/classes whose code range had **zero executed lines** in the E2E run.\n")
        lines.append("> Important: \"unused\" here means **not executed in this run**, not \"safe to delete\" by itself.\n\n")

        lines.append("## Summary\n")
        lines.append(f"- Total symbols: **{len(results)}**\n")
        lines.append(f"- Touched: **{len(touched)}**\n")
        lines.append(f"- Unused: **{len(unused)}**\n\n")

        lines.append("## Unused symbols (grouped by file)\n\n")
        by_file: Dict[Path, List[SymbolCoverageResult]] = {}
        for r in unused:
            by_file.setdefault(r.symbol.file_path, []).append(r)

        for file_path in sorted(by_file.keys(), key=lambda p: str(p)):
            rel = self._rel(file_path)
            lines.append(f"### `{rel}`\n\n")
            lines.append("| Kind | Qualified name | Lines | Notes |\n")
            lines.append("|---|---|---:|---|\n")
            for r in sorted(by_file[file_path], key=lambda x: (x.symbol.start_line, x.symbol.qualified_name)):
                span = f"{r.symbol.start_line}-{r.symbol.end_line}"
                notes = ", ".join(r.notes) if r.notes else ""
                lines.append(f"| {r.symbol.kind} | `{r.symbol.qualified_name}` | {span} | {notes} |\n")
            lines.append("\n")

        lines.append("## Touched symbols (optional sanity)\n\n")
        lines.append("This section is useful to validate that the E2E run actually exercised expected areas.\n\n")
        lines.append("| File | Kind | Qualified name | Executed/Total | Coverage |\n")
        lines.append("|---|---|---|---:|---:|\n")
        for r in sorted(touched, key=lambda x: (str(x.symbol.file_path), x.symbol.start_line)):
            rel = self._rel(r.symbol.file_path)
            frac = f"{r.executed_in_range}/{r.total_lines_in_range}"
            pct = f"{r.coverage_ratio*100:.1f}%"
            lines.append(f"| `{rel}` | {r.symbol.kind} | `{r.symbol.qualified_name}` | {frac} | {pct} |\n")

        return "".join(lines)

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_root))
        except ValueError:
            return str(path)


class CSVReporter:
    """Render analysis results into a CSV report with detailed information."""

    def __init__(self, repo_root: Path):
        """
        Initialize reporter.

        Args:
            repo_root: Repository root to make paths relative.
        """
        self.repo_root = repo_root.resolve()

    def render(self, results: Sequence[SymbolCoverageResult]) -> List[Dict[str, str]]:
        """
        Render analysis results as a list of dictionaries for CSV export.

        Args:
            results: Analysis results.

        Returns:
            List of dictionaries with CSV row data.
        """
        rows: List[Dict[str, str]] = []
        
        for result in results:
            if result.status != "unused":
                continue  # Only include unused symbols in CSV
                
            symbol = result.symbol
            rel_path = self._rel(symbol.file_path)
            
            # Extract code snippet
            code_snippet = self._extract_code_snippet(symbol.file_path, symbol.start_line, symbol.end_line)
            
            # Determine suggestion based on heuristics
            suggestion = self._determine_suggestion(symbol, result.notes)
            
            # Determine intended function/purpose
            intended_function = self._determine_intended_function(symbol)
            
            rows.append({
                "file_path": str(rel_path),
                "qualified_name": symbol.qualified_name,
                "kind": symbol.kind,
                "start_line": str(symbol.start_line),
                "end_line": str(symbol.end_line),
                "line_range": f"{symbol.start_line}-{symbol.end_line}",
                "code_snippet": code_snippet,
                "intended_function": intended_function,
                "notes": ", ".join(result.notes) if result.notes else "",
                "suggestion": suggestion,
                "executed_lines": str(result.executed_in_range),
                "total_lines": str(result.total_lines_in_range),
                "coverage_ratio": f"{result.coverage_ratio:.2%}",
                "is_async": str(symbol.is_async),
                "is_dunder": str(symbol.is_dunder),
                "decorators": ", ".join(symbol.decorators) if symbol.decorators else "",
            })
        
        return rows

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_root))
        except ValueError:
            return str(path)

    def _extract_code_snippet(self, file_path: Path, start_line: int, end_line: int) -> str:
        """
        Extract code snippet from file for the given line range.
        
        Args:
            file_path: Path to the file.
            start_line: Starting line number (1-indexed).
            end_line: Ending line number (1-indexed).
            
        Returns:
            Code snippet as a string.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Adjust for 0-indexed list
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            
            snippet_lines = lines[start_idx:end_idx]
            # Trim excessive whitespace and limit length
            snippet = ''.join(snippet_lines).strip()
            
            # Limit snippet length to avoid huge CSV cells
            max_length = 1000
            if len(snippet) > max_length:
                snippet = snippet[:max_length] + "... [truncated]"
                
            return snippet
            
        except Exception as e:
            return f"[Error reading file: {e}]"

    def _determine_suggestion(self, symbol: SymbolSpan, notes: Tuple[str, ...]) -> str:
        """
        Determine suggestion (delete/keep/correct) based on heuristics.
        
        Args:
            symbol: The symbol to analyze.
            notes: Notes from coverage analysis.
            
        Returns:
            Suggestion string.
        """
        notes_list = list(notes)
        
        # Heuristic rules
        if "file-not-in-coverage-json" in notes_list:
            return "investigate"  # File wasn't in coverage, need to check if it should be
        
        if symbol.is_dunder:
            # Dunder methods might be called implicitly
            if symbol.qualified_name in ["__init__", "__new__", "__call__"]:
                return "keep"  # Core dunder methods
            else:
                return "investigate"  # Less common dunder methods
        
        if "abstractmethod" in notes_list:
            return "keep"  # Abstract methods are meant to be overridden
        
        if "property" in notes_list:
            return "investigate"  # Properties might be accessed differently
        
        if symbol.kind == "class":
            # Classes might be imported and used elsewhere
            return "investigate"
        
        # Default suggestion for unused functions/methods
        return "consider_delete"

    def _determine_intended_function(self, symbol: SymbolSpan) -> str:
        """
        Determine the intended function/purpose of the symbol based on name and context.
        
        Args:
            symbol: The symbol to analyze.
            
        Returns:
            Description of intended function.
        """
        name = symbol.qualified_name.lower()
        
        # Common patterns
        if "test" in name:
            return "testing function"
        elif "main" == name:
            return "main entry point"
        elif "init" in name or "setup" in name:
            return "initialization/setup"
        elif "cleanup" in name or "teardown" in name:
            return "cleanup/teardown"
        elif "get" in name or "fetch" in name or "retrieve" in name:
            return "data retrieval"
        elif "set" in name or "update" in name or "save" in name:
            return "data modification"
        elif "validate" in name or "check" in name:
            return "validation/checking"
        elif "process" in name or "handle" in name:
            return "data processing"
        elif "parse" in name or "read" in name:
            return "parsing/reading"
        elif "write" in name or "save" in name:
            return "writing/saving"
        elif "calculate" in name or "compute" in name:
            return "calculation/computation"
        elif "format" in name or "render" in name:
            return "formatting/rendering"
        elif "log" in name or "debug" in name:
            return "logging/debugging"
        elif "error" in name or "exception" in name:
            return "error handling"
        elif "helper" in name or "util" in name:
            return "utility/helper function"
        else:
            return "general purpose"


class UnusedSymbolAuditApp:
    """CLI application for producing unused symbol reports."""

    def __init__(self, repo_root: Path, coverage_json: Path, out_path: Path, 
                 format: str = "markdown", csv_out: Optional[Path] = None):
        """
        Initialize application.

        Args:
            repo_root: Repository root.
            coverage_json: Path to coverage.json exported by coverage.
            out_path: Output markdown file path.
            format: Output format ("markdown" or "csv").
            csv_out: Optional separate CSV output path.
        """
        self.repo_root = repo_root.resolve()
        self.coverage_json = coverage_json.resolve()
        self.out_path = out_path.resolve()
        self.format = format
        self.csv_out = csv_out.resolve() if csv_out else None

    def run(self) -> None:
        """
        Execute the audit:
        - Load coverage JSON
        - Walk repo and parse AST
        - Analyze symbol coverage
        - Write report(s)
        """
        exclude_dirs = [
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "node_modules",
            "coverage_reports",
            "dist",
            "build",
        ]

        coverage_data = CoverageJsonLoader(self.coverage_json, self.repo_root).load()
        walker = RepoWalker(self.repo_root, exclude_dirs=exclude_dirs)

        symbols: List[SymbolSpan] = []
        for file_path in walker.iter_python_files():
            symbols.extend(self._extract_symbols(file_path))

        analyzer = SymbolCoverageAnalyzer(self.repo_root, coverage_data)
        results = analyzer.analyze(symbols)

        # Generate markdown report
        if self.format in ["markdown", "both"]:
            report = MarkdownReporter(self.repo_root).render(results)
            self.out_path.write_text(report, encoding="utf-8")
            print(f"Markdown report written to: {self.out_path}")

        # Generate CSV report
        if self.format in ["csv", "both"]:
            csv_path = self.csv_out or self.out_path.with_suffix(".csv")
            csv_reporter = CSVReporter(self.repo_root)
            rows = csv_reporter.render(results)
            
            if rows:
                self._write_csv(csv_path, rows)
                print(f"CSV report written to: {csv_path}")
                print(f"Total unused symbols in CSV: {len(rows)}")
            else:
                print("No unused symbols found for CSV report.")

    def _extract_symbols(self, file_path: Path) -> List[SymbolSpan]:
        """
        Parse a Python file into AST and extract symbol spans.

        Args:
            file_path: Python file path.

        Returns:
            List of SymbolSpan.
        """
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = file_path.read_text(encoding="utf-8", errors="ignore")

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        extractor = PythonSymbolExtractor(file_path)
        extractor.visit(tree)
        return extractor.symbols

    def _write_csv(self, csv_path: Path, rows: List[Dict[str, str]]) -> None:
        """
        Write CSV file with the given rows.
        
        Args:
            csv_path: Path to write CSV file.
            rows: List of dictionaries with CSV data.
        """
        if not rows:
            return
            
        # Define field order
        fieldnames = [
            "file_path",
            "qualified_name", 
            "kind",
            "start_line",
            "end_line",
            "line_range",
            "intended_function",
            "suggestion",
            "notes",
            "executed_lines",
            "total_lines",
            "coverage_ratio",
            "is_async",
            "is_dunder",
            "decorators",
            "code_snippet",
        ]
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List unused functions/methods/classes using coverage JSON × AST."
    )
    parser.add_argument(
        "--repo-root", 
        required=True, 
        help="Repository root directory"
    )
    parser.add_argument(
        "--coverage-json", 
        required=True, 
        help="Path to coverage JSON file (from `coverage json -o ...`)"
    )
    parser.add_argument(
        "--out", 
        required=True, 
        help="Output file path (markdown by default, CSV if --format=csv)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "csv", "both"],
        default="markdown",
        help="Output format: markdown, csv, or both (default: markdown)"
    )
    parser.add_argument(
        "--csv-out",
        help="Optional separate CSV output path (used with --format=both)"
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    app = UnusedSymbolAuditApp(
        repo_root=Path(args.repo_root),
        coverage_json=Path(args.coverage_json),
        out_path=Path(args.out),
        format=args.format,
        csv_out=Path(args.csv_out) if args.csv_out else None,
    )
    app.run()


if __name__ == "__main__":
    main()
