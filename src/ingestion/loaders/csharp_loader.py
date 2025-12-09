"""Module for C# code structure representation."""

import re


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
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        out = []
        for i, line in enumerate(lines, start=1):
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
