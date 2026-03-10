"""Helper to list pytest tests missing @readable metadata."""

import ast
from pathlib import Path
from typing import Iterable


def _decorator_is_readable(decorator: ast.expr) -> bool:
    target = decorator
    if isinstance(decorator, ast.Call):
        target = decorator.func
    if isinstance(target, ast.Name) and target.id == "readable":
        return True
    if isinstance(target, ast.Attribute) and target.attr == "readable":
        return True
    return False


def _function_has_readable(node: ast.FunctionDef) -> bool:
    return any(_decorator_is_readable(decorator) for decorator in node.decorator_list)


def _iter_test_functions(tree: ast.AST) -> Iterable[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            yield node


def main(test_root: Path | None = None) -> int:
    root = test_root or Path("tests")
    missing = []
    for path in sorted(root.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (UnicodeDecodeError, SyntaxError):
            continue
        for func in _iter_test_functions(tree):
            if not _function_has_readable(func):
                missing.append((path, func.name))
    if missing:
        print("Functions missing @readable:")
        for path, name in missing:
            print(f"{path}:{name}")
        return 1
    print("All test functions already have @readable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
