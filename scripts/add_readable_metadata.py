"""Insert or refresh pytest-readable decorators in test functions."""

import ast
import re
from pathlib import Path
from typing import Iterable, Sequence


READABLE_IMPORT = "from pytest_readable import readable\n"
TARGET_ROOTS = (Path("tests"), Path("experiments/swarm_rag/tests"))


class TestFunctionVisitor:
    """Collect top-level test functions and test methods."""

    def __init__(self) -> None:
        self.items: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None]] = []

    def visit_module(self, tree: ast.Module) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str | None]]:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                self.items.append((node, None))
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                        self.items.append((child, node.name))
        return self.items


def _decorator_is_readable(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id == "readable"
    if isinstance(target, ast.Attribute):
        return target.attr == "readable"
    return False


def _has_readable(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_is_readable(decorator) for decorator in node.decorator_list)


def _split_words(name: str) -> list[str]:
    return [word for word in name.replace("test_", "").split("_") if word]


def _camel_to_words(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value).strip()


def _summary_from_name(name: str, class_name: str | None) -> str:
    words = _split_words(name)
    phrase = " ".join(words) if words else name
    if class_name:
        class_phrase = _camel_to_words(class_name.replace("Test", "")).replace("_", " ").strip()
        if class_phrase:
            return f"Verify {phrase} in {class_phrase.lower()}."
    return f"Verify {phrase}."


def _docstring_summary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    docstring = ast.get_docstring(node)
    if not docstring:
        return None
    first_line = docstring.strip().splitlines()[0].strip()
    if not first_line:
        return None
    if first_line[-1] not in ".!?":
        first_line = f"{first_line}."
    return first_line[0].upper() + first_line[1:]


def _build_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None) -> list[str]:
    indent = " " * node.col_offset
    summary = _docstring_summary(node) or _summary_from_name(node.name, class_name)
    scenario = " ".join(_split_words(node.name)) or node.name
    return [
        f"{indent}@readable(\n",
        f'{indent}    intent="{summary.replace(chr(34), chr(39))}",\n',
        f"{indent}    steps=[\n",
        f'{indent}        "Set up the inputs and collaborators for the scenario.",\n',
        f'{indent}        "Run the {scenario} behavior under test.",\n',
        f'{indent}        "Check the observable result and assertions.",\n',
        f"{indent}    ],\n",
        f"{indent}    criteria=[\n",
        f'{indent}        "The assertions confirm the documented behavior.",\n',
        f"{indent}    ],\n",
        f"{indent})\n",
    ]


def _import_present(lines: Sequence[str]) -> bool:
    return any(line.strip() == READABLE_IMPORT.strip() for line in lines)


def _find_import_insertion_line(tree: ast.Module) -> int:
    insert_after = 0
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.lineno == 1
        ):
            insert_after = node.end_lineno or node.lineno
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_after = node.end_lineno or node.lineno
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_after = node.end_lineno or node.lineno
            continue
        break
    return insert_after


def _apply_to_file(path: Path) -> bool:
    source = path.read_text()
    tree = ast.parse(source)
    discovered_tests = TestFunctionVisitor().visit_module(tree)
    if not discovered_tests:
        return False

    lines = source.splitlines(keepends=True)
    updated = False
    for node, class_name in sorted(discovered_tests, key=lambda item: item[0].lineno, reverse=True):
        generated_block = _build_decorator(node, class_name)
        if not _has_readable(node):
            insert_at = (node.decorator_list[-1].end_lineno if node.decorator_list else node.lineno) - 1
            lines[insert_at:insert_at] = generated_block
            updated = True
            continue

        readable_decorator = next(
            decorator for decorator in node.decorator_list if _decorator_is_readable(decorator)
        )
        start = readable_decorator.lineno - 1
        end = (readable_decorator.end_lineno or readable_decorator.lineno)
        current_block = lines[start:end]
        if any("The test assertions confirm the documented behavior." in line for line in current_block):
            lines[start:end] = generated_block
            updated = True

    if not _import_present(lines):
        insert_at = _find_import_insertion_line(tree)
        import_block = [READABLE_IMPORT]
        if insert_at > 0 and lines[insert_at - 1].strip():
            import_block.append("\n")
        lines[insert_at:insert_at] = import_block
        updated = True

    if updated:
        path.write_text("".join(lines))
    return updated


def _iter_targets(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        yield from sorted(root.rglob("test_*.py"))


def main() -> int:
    updated = 0
    for path in _iter_targets(TARGET_ROOTS):
        if _apply_to_file(path):
            updated += 1
            print(path)
    print(f"Updated {updated} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
