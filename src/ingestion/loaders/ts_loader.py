"""Module for TypeScript code structure representation."""


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
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        out = []
        for i, line in enumerate(lines, start=1):
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
