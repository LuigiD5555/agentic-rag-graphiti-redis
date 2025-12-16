"""Module for Java code structure representation."""

import re


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
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
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
