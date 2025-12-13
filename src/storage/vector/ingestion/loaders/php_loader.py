"""Module for PHP code structure representation."""


class PHPCodeStructure:
    """Represent the structure of a PHP source file."""

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a PHP file.

        Returns:
            str: Summary of key declarations.
        """
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        out = []
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                continue

            if stripped.startswith(("function ", "class ", "interface ", "trait ")):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith("<?php") or stripped.startswith("namespace ") or stripped.startswith("use "):
                continue

        return "\n".join(out) if out else "File structure only"
