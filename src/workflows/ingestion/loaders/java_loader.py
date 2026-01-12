"""Module for Java code structure representation."""

import re

from src.workflows.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.workflows.ingestion.pipeline.utils.text_reading import read_text_with_fallbacks


class JavaCodeStructure:
    """Represent the structure of a Java source file."""

    _METHOD_PATTERN = re.compile(
        r"""
        ^\s*
        (?:public|protected|private)?\s*
        (?:static\s+)?(?:final\s+)?(?:synchronized\s+)?     # modifiers
        [\w\<\>\[\]]+\s+                                     # return type
        [a-zA-Z_]\w*\s*\([^;]*\)\s*                          # method name + params
        \{?$
        """,
        re.VERBOSE,
    )

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a Java file.

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

            if stripped.startswith(("class ", "interface ", "enum ", "record ")):
                out.append(f"Line {i}: {stripped}")
            elif self._METHOD_PATTERN.match(stripped):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith("package ") or stripped.startswith("import "):
                continue

        return "\n".join(out) if out else "File structure only"
