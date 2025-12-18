"""Module for C# code structure representation."""

import re

from src.rag.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.utils.text_reading import read_text_with_fallbacks


class CSharpCodeStructure:
    """Represent the structure of a C# source file."""

    _METHOD_PATTERN = re.compile(
        r"""
        ^\s*
        (?:public|private|protected|internal)?\s*
        (?:static\s+)?(?:async\s+)?(?:partial\s+)?      # modifiers
        [\w\<\>\[\]]+\s+                                # return type
        [a-zA-Z_]\w*\s*\([^;]*\)\s*
        (?:\{|=>)?$
        """,
        re.VERBOSE,
    )

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a C# file.

        Returns:
            str: Summary of key declarations.
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
            if not stripped or stripped.startswith("//"):
                continue

            if stripped.startswith(("class ", "interface ", "struct ", "record ")):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith("namespace "):
                out.append(f"Line {i}: {stripped}")
            elif self._METHOD_PATTERN.match(stripped):
                out.append(f"Line {i}: {stripped}")

        return "\n".join(out) if out else "File structure only"
