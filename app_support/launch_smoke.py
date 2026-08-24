"""Everything a launcher's entry point imports, read off its AST and replayed.

A windowed launch has no console. An import that fails inside one writes its
traceback nowhere at all, so the icon simply does nothing while the suite stays
entirely green — the tests import the module and stop at the top of it, and every
import a ``main()`` performs is below that line. The launcher gets no help from a
``conftest.py`` either, so what resolves at launch is not what resolves under
pytest.

So: walk the files the launch actually executes, collect the imports it will
really perform, and replay them in a fresh interpreter started the way the
launcher starts one. Off the AST rather than off a list kept by hand, because a
hand-written list is exactly what drifts — the next lazy import added to a
``main()`` would not be in it, and the guard would quietly stop covering the
thing it was written for. Replayed as whole ``from X import a, b`` statements
rather than as ``import X``, so a symbol the launch names but the module no
longer defines fails here too.

Starting that interpreter is the one thing this cannot do for you: each launcher
has its own interpreter, working directory and environment, and those are the
part worth being exact about. Pass a callable that runs the statements that
launcher's way, and hand it to the assertions here:

    STATEMENTS = launch_imports("myapp", [ENTRY, APP])

    def test_the_launch_imports_everything_it_names():
        assert_every_import_resolves(_run_the_launchs_way, STATEMENTS)

    def test_the_walk_reaches_the_imports_buried_in_main():
        assert_the_walk_reached(STATEMENTS, ["myapp.state"])

    def test_a_launch_import_that_cannot_resolve_fails_here():
        assert_an_unresolvable_import_is_caught(
            _run_the_launchs_way, STATEMENTS, "myapp.state")

The third is not optional. Without it every assertion above can pass for the
empty reason — a replay that reports success regardless, or a walk that found
nothing to replay — and the guard becomes decorative in the exact silence it
exists to break.

Standard library only, and no pytest: these are plain functions raising
``AssertionError``, so importing this costs a repo nothing at run time.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Callable, Iterable, Sequence

# Only these two. A broad ``except Exception`` around a launch body is an error
# *reporter* -- it puts a dialog on screen or writes a crash log -- so an import
# inside it is required, not optional: it failing is exactly the launch failure
# this exists to catch.
TOLERATED_BY = frozenset({"ImportError", "ModuleNotFoundError"})

#: Runs the given statements the way one launcher starts its interpreter.
Replay = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING:`` bodies are never executed, at launch or anywhere."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _tolerates_a_missing_module(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:  # bare except -- catches everything, promises nothing
            return False
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        if any(isinstance(n, ast.Name) and n.id in TOLERATED_BY for n in caught):
            return True
    return False


def _optional_imports(tree: ast.Module) -> set[int]:
    """Imports whose absence the module already handles, so the launch survives
    them and this must not insist on them."""
    optional: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            body = node.body
        elif isinstance(node, ast.Try) and _tolerates_a_missing_module(node.handlers):
            body = node.body
        else:
            continue
        for statement in body:
            for inner in ast.walk(statement):
                optional.add(id(inner))
    return optional


def _render(node: ast.Import | ast.ImportFrom, package: str) -> str:
    """The import statement as the launch executes it, relative made absolute.

    A launch file sits at the top of its package, so a relative import is never
    deeper than one level. A launcher that runs a bare script rather than a
    package passes ``package=""``; such a file cannot contain a relative import
    at all, since Python itself would refuse to execute one.
    """
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    if isinstance(node, ast.Import):
        return f"import {names}"
    assert node.level <= 1, f"unexpected relative import depth in {package}"
    module = node.module or ""
    if node.level:
        module = f"{package}.{module}" if module else package
    return f"from {module} import {names}"


def _is_a_compiler_directive(node: ast.Import | ast.ImportFrom) -> bool:
    """``from __future__ import ...`` loads no module -- it is a flag to the
    compiler, and it is only legal at the top of a file, so replaying it among
    the others is a SyntaxError rather than a check of anything."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def launch_imports(package: str, launch_files: Iterable[Path]) -> list[str]:
    """Every import *launch_files* will actually perform, as replayable source.

    *package* is what a relative import resolves against -- the package the
    launcher runs with ``-m``, or ``""`` for a launcher that runs a loose script.
    """
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


# Every assertion below carries its whole diagnostic in the message, and hides
# its own frame. Living outside pytest means pytest's assertion rewriting never
# rewrites these -- a bare `assert x == 0` here would fail with no explanation at
# all, and the report would point into this file rather than at the repo's test
# that called it.


def _replay_report(result) -> str:
    return (f"exit {result.returncode}\n"
            f"--- stderr ---\n{result.stderr}\n--- stdout ---\n{result.stdout}")


def assert_every_import_resolves(replay: Replay, statements: list[str]) -> None:
    """Failing here means that shortcut does nothing: the launcher has no
    console, so the traceback from a failed import goes nowhere at all."""
    __tracebackhide__ = True
    result = replay(statements)

    assert result.returncode == 0, (
        f"the launch's own imports do not resolve:\n{_replay_report(result)}")


def assert_the_walk_reached(statements: Sequence[str], modules: Iterable[str]) -> None:
    """The guard above is only worth anything if the walk found the lazy imports.

    Name the modules the launch reaches only from inside a ``main()``. A walk
    that silently found nothing -- a renamed file, a parse that returned an empty
    tree -- would otherwise sail through every other check here, because there is
    nothing left to fail on.
    """
    __tracebackhide__ = True
    found = "\n".join(statements)
    for module in modules:
        assert module in found, (
            f"the launch imports {module}; the walk missed it. "
            f"The walk found {len(statements)} statements.")


def assert_an_unresolvable_import_is_caught(
    replay: Replay, statements: list[str], through_module: str,
) -> None:
    """The negative control: if the replay reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative.

    *through_module* is any module the launch really imports; a symbol that
    cannot exist is asked of it, and the replay has to fail on exactly that.
    """
    __tracebackhide__ = True
    result = replay([*statements, f"from {through_module} import NoSuchSymbol"])

    assert result.returncode != 0, (
        "a symbol that cannot exist imported cleanly, so this replay proves "
        f"nothing and every check built on it is decorative:\n{_replay_report(result)}")
    assert "NoSuchSymbol" in result.stderr, (
        f"the replay failed, but not on the planted symbol -- so what it proves "
        f"is that the replay is broken, not that it is watching:\n"
        f"{_replay_report(result)}")
