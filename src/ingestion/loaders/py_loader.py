"""Module for Python code structure representation."""

from src.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.ingestion.pipeline.utils.text_reading import read_text_with_fallbacks


class PythonCodeStructure:
    """Class to represent the structure of a Python file."""
    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a Python file

        Returns:
            str: Summary of the file structure.
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
            s = line.strip()
            if s.startswith("def ") or s.startswith("class "):
                out.append(f"Line {i}: {s}")
        return "\n".join(out) if out else "File structure only"
