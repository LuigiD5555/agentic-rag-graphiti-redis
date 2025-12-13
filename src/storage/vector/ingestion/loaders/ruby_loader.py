"""Module for Ruby code structure representation."""


class RubyCodeStructure:
    """Represent the structure of a Ruby source file."""

    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a Ruby file.

        Returns:
            str: Summary of key declarations.
        """
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        out = []
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith(("def ", "class ", "module ")):
                out.append(f"Line {i}: {stripped}")
            elif stripped.startswith("attr_"):
                out.append(f"Line {i}: {stripped}")

        return "\n".join(out) if out else "File structure only"
