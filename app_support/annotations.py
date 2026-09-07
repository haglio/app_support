"""Every module defers its annotations, so two Python versions read it the same way.

3.14 evaluates annotations lazily (PEP 649) and 3.12 evaluates them as the
``def`` executes.  The machine this family is developed on runs 3.14 and every
merge gate runs 3.12, so a signature naming something its module does not bind
imports fine locally and raises ``NameError`` at collection in CI: a branch that
is green on the desk and cannot be collected by the gate.  That has happened, and
origenerator carries a hundred-line static guard written the day it did.

``from __future__ import annotations`` removes the disagreement rather than
policing it -- nothing in the file is evaluated on either version -- and 884 of
the family's 1,380 modules already have it.  This is the check that closes the
gap and keeps it closed::

    from app_support.annotations import assert_every_module_defers_annotations

    def test_every_module_defers_its_annotations():
        assert_every_module_defers_annotations(
            ROOT, [ROOT / "the_package", ROOT / "tests"])

An empty module is left alone: the ``__init__.py`` files that exist only to make
a package are most of them, and there is nothing in one for two versions to
disagree about.  Standard library only.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

FIX = ('ruff check --select I002 --fix '
       '--config \'lint.isort.required-imports = ["from __future__ import annotations"]\'')


def _defers(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _is_empty(tree: ast.Module) -> bool:
    """Nothing but a docstring, so no annotation can live here."""
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return not body


def modules_evaluating_their_annotations(root: Path, packages: Iterable[Path]) -> list[str]:
    """The modules under *packages* that 3.12 and 3.14 could read differently."""
    found = []
    for package in packages:
        paths = [package] if Path(package).is_file() else sorted(Path(package).rglob("*.py"))
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            if not _defers(tree) and not _is_empty(tree):
                found.append(path.relative_to(root).as_posix())
    return sorted(found)


def assert_every_module_defers_annotations(root: Path, packages: Iterable[Path]) -> None:
    evaluating = modules_evaluating_their_annotations(root, packages)
    assert not evaluating, (
        "These modules evaluate their annotations, so the gate's Python and this "
        "machine's can disagree about them:\n  " + "\n  ".join(evaluating)
        + f"\n\nAdd the import to all of them with:\n  {FIX}")
