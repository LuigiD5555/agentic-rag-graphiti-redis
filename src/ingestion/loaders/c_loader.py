"""Module for C and C++ code structure representation."""

import re

from src.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.utils.text_reading import read_text_with_fallbacks


class CCodeStructure:
    """Represent structure of a C/C++ source file."""

    _FUNCTION_PATTERN = re.compile(
        r"""
        ^\s*                                  # leading whitespace
        (?:[a-zA-Z_][\w\s\*\d]*\s+)?          # optional return type tokens
        [a-zA-Z_]\w*                          # function name
        \s*\([^;]*\)\s*                       # parameters (ignore prototypes with ;)
        (?:\{|$)                              # brace or newline
        """,
        re.VERBOSE,
    )

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a C/C++ file by capturing high-level declarations.

        Returns:
            str: Summary of notable declarations.
        """
        ensure_file_exists(self.path)
        try:
            result = read_text_with_fallbacks(self.path)
        except ValueError as exc:
            raise LoaderUnreadableTextError(self.path, str(exc)) from exc
        except UnicodeDecodeError as exc:
            raise LoaderUnreadableTextError(self.path, str(exc)) from exc

        out: list[str] = []
        for i, line in enumerate(result.text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                continue

            if self._is_function_signature(stripped):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith(("struct ", "enum ", "class ", "typedef ")):
                out.append(f"Line {i}: {stripped}")

        return "\n".join(out) if out else "File structure only"

    def _is_function_signature(self, line: str) -> bool:
        """Heuristically detect function signatures while skipping prototypes."""
        if line.endswith(";"):
            return False  # likely a prototype or declaration
        return bool(self._FUNCTION_PATTERN.match(line))
