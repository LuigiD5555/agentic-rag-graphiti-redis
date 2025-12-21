"""Module for TypeScript code structure representation."""

from src.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.ingestion.pipeline.utils.text_reading import read_text_with_fallbacks


class TypeScriptCodeStructure:
    """Represent the structure of a TypeScript source file."""

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a TypeScript file.

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

            if stripped.startswith((
                "function ",
                "export function",
                "class ",
                "export class",
                "interface ",
                "export interface",
                "type ",
                "export type",
                "enum ",
                "export enum",
            )):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith("const ") and "=>" in stripped:
                out.append(f"Line {i}: {stripped}")

        return "\n".join(out) if out else "File structure only"
