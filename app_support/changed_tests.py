"""Name the tests a branch added or changed, so a gate can run those ten times."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import NamedTuple

__all__ = ["changed_test_ids"]

_MODULE_LEVEL = ""


class _Module(NamedTuple):
    tests: dict[tuple[str, str], str]
    around: dict[str, list[str]]
    imports: set[str]


def changed_test_ids(root: Path, base: str) -> list[str]:
    ids: list[str] = []
    for path in _changed_test_files(root, base):
        before = _read(root, f"{base}:{path}")
        after = _read(root, f"HEAD:{path}")
        for (klass, test), body in after.tests.items():
            if before.tests.get((klass, test)) != body or _around_changed(before, after, klass):
                ids.append("::".join(part for part in (path, klass, test) if part))
    return ids


def _around_changed(before: _Module, after: _Module, klass: str) -> bool:
    return (not before.imports <= after.imports
            or any(before.around.get(scope) != after.around.get(scope)
                   for scope in {_MODULE_LEVEL, klass}))


def _changed_test_files(root: Path, base: str) -> list[str]:
    out = _git(root, "diff", "--name-only", f"{base}...HEAD")
    return [n for n in out.splitlines() if Path(n).name.startswith("test_") and n.endswith(".py")]


def _read(root: Path, revision_and_path: str) -> _Module:
    tests: dict[tuple[str, str], str] = {}
    around: dict[str, list[str]] = {_MODULE_LEVEL: []}
    imports: set[str] = set()
    for node in _without_docstring(ast.parse(_source(root, revision_and_path)).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.add(ast.dump(node))
        elif _is_test(node):
            tests[_MODULE_LEVEL, node.name] = ast.dump(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            around[node.name] = []
            for inner in node.body:
                if _is_test(inner):
                    tests[node.name, inner.name] = ast.dump(inner)
                else:
                    around[node.name].append(ast.dump(inner))
        else:
            around[_MODULE_LEVEL].append(ast.dump(node))
    return _Module(tests, around, imports)


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return body[1:]
    return body


def _source(root: Path, revision_and_path: str) -> str:
    """Empty where the file is not in that revision at all -- a file the branch
    adds has no earlier self, and every test in it is new."""
    try:
        return _git(root, "show", revision_and_path)
    except subprocess.CalledProcessError:
        return ""


def _is_test(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(root), *args],
                          check=True, capture_output=True, text=True)
    return done.stdout
