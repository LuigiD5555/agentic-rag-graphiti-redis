"""Module for Go code structure representation."""


class GoCodeStructure:
    """Represent the structure of a Go source file."""

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a Go file.

        Returns:
            str: Summary of key declarations.
        """
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue

                if stripped.startswith("func "):
                    out.append(f"Line {i}: {stripped}")
                elif stripped.startswith(("type ", "const ", "var ")):
                    out.append(f"Line {i}: {stripped}")
                elif stripped.startswith("package ") or stripped.startswith("import "):
                    continue

        return "\n".join(out) if out else "File structure only"
