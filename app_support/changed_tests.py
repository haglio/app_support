"""Name the tests a branch added or changed, so a gate can run those ten times."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import NamedTuple

__all__ = ["changed_test_ids"]

_MODULE_LEVEL = ""
_EVERY_TEST = "pytestmark"


class _Module(NamedTuple):
    tests: dict[tuple[str, str], str]
    reaches: dict[tuple[str, str], set[str]]
    defined: dict[str, list[str]]
    unfollowed: list[str]
    in_class: dict[str, list[str]]
    imports: set[str]


def changed_test_ids(root: Path, base: str) -> list[str]:
    ids: list[str] = []
    for path in _changed_test_files(root, base):
        before = _read(root, f"{base}:{path}")
        after = _read(root, f"HEAD:{path}")
        moved = _definitions_that_moved(before, after)
        for (klass, test), body in after.tests.items():
            if (before.tests.get((klass, test)) != body
                    or _around_changed(before, after, klass)
                    or moved & after.reaches[klass, test]):
                ids.append("::".join(part for part in (path, klass, test) if part))
    return ids


def _around_changed(before: _Module, after: _Module, klass: str) -> bool:
    return (not before.imports <= after.imports
            or before.unfollowed != after.unfollowed
            or before.in_class.get(klass) != after.in_class.get(klass))


def _definitions_that_moved(before: _Module, after: _Module) -> set[str]:
    return {name for name in before.defined.keys() | after.defined.keys()
            if before.defined.get(name) != after.defined.get(name)}


def _changed_test_files(root: Path, base: str) -> list[str]:
    out = _git(root, "diff", "--name-only", f"{base}...HEAD")
    return [n for n in out.splitlines() if Path(n).name.startswith("test_") and n.endswith(".py")]


def _read(root: Path, revision_and_path: str) -> _Module:
    tests: dict[tuple[str, str], str] = {}
    mentions: dict[tuple[str, str], set[str]] = {}
    defined: dict[str, list[str]] = {}
    mentioned_by: dict[str, set[str]] = {}
    unfollowed: list[str] = []
    in_class: dict[str, list[str]] = {}
    imports: set[str] = set()
    for node in _without_docstrings(ast.parse(_source(root, revision_and_path))).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports |= _bound_by(node)
        elif _is_test(node):
            tests[_MODULE_LEVEL, node.name] = ast.dump(node)
            mentions[_MODULE_LEVEL, node.name] = _mentions(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            in_class[node.name] = []
            for inner in node.body:
                if _is_test(inner):
                    tests[node.name, inner.name] = ast.dump(inner)
                    mentions[node.name, inner.name] = _mentions(inner)
                else:
                    in_class[node.name].append(ast.dump(inner))
        elif names := _defined_by(node):
            for name in names:
                defined.setdefault(name, []).append(ast.dump(node))
                mentioned_by.setdefault(name, set()).update(_mentions(node))
        else:
            unfollowed.append(ast.dump(node))
    reaches = {test: _everything_reached(named, mentioned_by) for test, named in mentions.items()}
    return _Module(tests, reaches, defined, unfollowed, in_class, imports)


def _defined_by(node: ast.stmt) -> set[str]:
    """The module-level names this statement binds, and nothing for one the walk
    below cannot follow -- a rebinding, a tuple target, a bare statement, a mark
    or fixture that reaches tests which never name it.  Those fall back to the
    whole file, where a name has only the tests that mention it to answer for."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set() if _reaches_every_test(node) else {node.name}
    if isinstance(node, ast.ClassDef):
        return {node.name}
    assigned = _assigned_names(node)
    return set() if _EVERY_TEST in assigned else assigned


def _assigned_names(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.Assign) and all(isinstance(at, ast.Name) for at in node.targets):
        return {at.id for at in node.targets}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def _reaches_every_test(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(word.arg == "autouse" and getattr(word.value, "value", False)
               for decorator in node.decorator_list if isinstance(decorator, ast.Call)
               for word in decorator.keywords)


def _mentions(node: ast.AST) -> set[str]:
    """Every name the node could be reaching: what it writes out, the arguments
    it takes -- a test's are the fixtures it asks for -- and the words of any
    string a decorator carries, which is how ``usefixtures`` names one."""
    spoken = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
    spoken |= {taken.arg for inner in ast.walk(node)
               if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
               for taken in inner.args.args}
    spoken |= {word for decorator in getattr(node, "decorator_list", [])
               for inner in ast.walk(decorator)
               if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
               for word in inner.value.replace(",", " ").split()}
    return spoken


def _everything_reached(mentioned: set[str], mentioned_by: dict[str, set[str]]) -> set[str]:
    """What a test touches through the file's own definitions, however many
    helpers deep -- a helper that calls a helper is still the test's to answer
    for, and a name gone from the file is kept so its loss still counts."""
    reached = set(mentioned)
    todo = [name for name in mentioned if name in mentioned_by]
    while todo:
        for further in mentioned_by[todo.pop()]:
            if further not in reached:
                reached.add(further)
                if further in mentioned_by:
                    todo.append(further)
    return reached


def _bound_by(node: ast.Import | ast.ImportFrom) -> set[str]:
    """Where a name comes from is where the test's subject lives, not what the
    test does -- so a module that moved rewrites the line and changes nothing.  A
    star import carries its module instead, its names being unknowable."""
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return {f"*{node.level * '.'}{node.module or ''}" if alias.name == "*"
            else alias.asname or alias.name for alias in node.names}


_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _without_docstrings(tree: ast.Module) -> ast.Module:
    """Every scope's, not only the file's: nothing runs a docstring, so no
    rewrite of one can turn a test flaky."""
    for node in ast.walk(tree):
        if isinstance(node, _SCOPES):
            node.body = _past_the_docstring(node.body)
    return tree


def _past_the_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
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
    """Named encoding, not the machine's: a source file is UTF-8 wherever it is
    read, and Windows' own code page cannot decode five of its bytes."""
    done = subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, encoding="utf-8")
    return done.stdout
