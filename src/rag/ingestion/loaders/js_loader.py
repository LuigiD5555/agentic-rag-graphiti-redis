"""Module for JavaScript code structure representation"""


class JavaScriptCodeStructure:
    """
    Class to represent the structure of a JavaScript file.
    """
    def __init__(self, path: str):
        self.path = path

    def load_structure_summary(self) -> str:
        """
        Load the structure of a JavaScript file

        Returns:
            str: Summary of the file structure.
        """
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                s = line.strip()
                if s.startswith("function ") or s.startswith("class "):
                    out.append(f"Line {i}: {s}")
        return "\n".join(out) if out else "File structure only"
