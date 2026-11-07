from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

TOLERATED_BY = frozenset({"ImportError", "ModuleNotFoundError"})

RunsTheStatementsTheLaunchersWay = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _tolerates_a_missing_module(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:
            return False
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        if any(isinstance(n, ast.Name) and n.id in TOLERATED_BY for n in caught):
            return True
    return False


def _optional_imports(tree: ast.Module) -> set[int]:
    optional: set[int] = set()
    for node in ast.walk(tree):
        if ((isinstance(node, ast.If) and _is_type_checking(node.test))
                or (isinstance(node, ast.Try) and _tolerates_a_missing_module(node.handlers))):
            body = node.body
        else:
            continue
        for statement in body:
            for inner in ast.walk(statement):
                optional.add(id(inner))
    return optional


def _render(node: ast.Import | ast.ImportFrom, package: str) -> str:
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    if isinstance(node, ast.Import):
        return f"import {names}"
    assert node.level <= 1, f"a launch file sits at the top of {package}, so a relative import there is never deeper than one level"
    module = node.module or ""
    # CPython refuses a relative import in a file run as a bare script, so an empty package needs no branch here.
    if node.level:
        module = f"{package}.{module}" if module else package
    return f"from {module} import {names}"


def _is_a_compiler_directive(node: ast.Import | ast.ImportFrom) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def launch_imports(package: str, launch_files: Iterable[Path]) -> list[str]:
    statements: list[str] = []
    for path in launch_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        optional = _optional_imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in optional or _is_a_compiler_directive(node):
                continue
            statements.append(_render(node, package))
    return statements


# Outside pytest, so its assertion rewriting never applies here: a bare `assert x == 0` would fail
# with no explanation, so every assertion carries its whole diagnostic in the message, and hides its
# own frame with pytest's __tracebackhide__ so the report points at the repo's test that called it.


def _replay_report(result) -> str:
    return (f"exit {result.returncode}\n"
            f"--- stderr ---\n{result.stderr}\n--- stdout ---\n{result.stdout}")


def assert_every_import_resolves(replay: RunsTheStatementsTheLaunchersWay, statements: list[str]) -> None:
    __tracebackhide__ = True
    result = replay(statements)

    assert result.returncode == 0, (
        "the launch's own imports do not resolve, which a windowed launch would have shown no traceback for:\n"
        f"{_replay_report(result)}")


def assert_the_walk_reached(statements: Sequence[str], reached_only_inside_main: Iterable[str]) -> None:
    __tracebackhide__ = True
    found = "\n".join(statements)
    for module in reached_only_inside_main:
        assert module in found, (
            f"the launch imports {module}; the walk missed it. "
            f"The walk found {len(statements)} statements.")


def assert_an_unresolvable_import_is_caught(
    replay: RunsTheStatementsTheLaunchersWay, statements: list[str], through_module: str,
) -> None:
    __tracebackhide__ = True
    result = replay([*statements, f"from {through_module} import NoSuchSymbol"])

    assert result.returncode != 0, (
        "a symbol that cannot exist imported cleanly, so this replay proves "
        f"nothing and every check built on it is decorative:\n{_replay_report(result)}")
    assert "NoSuchSymbol" in result.stderr, (
        f"the replay failed, but not on the planted symbol -- so what it proves "
        f"is that the replay is broken, not that it is watching:\n"
        f"{_replay_report(result)}")
