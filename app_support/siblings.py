"""Where the other checkouts of the family are, asked one way.

The family's repos are cloned side by side, and an app that needs a sibling --
its shared widgets, the players' core, Fun Time's favorites file -- asked where
it was in eight independent ways, four of them by spelling the directory's name
into a path count.  Two of them put the sibling on ``sys.path`` with opposite
ideas about where: one at the front, where the sibling's own ``tests`` and
``tools`` packages then shadowed the app's, and one at the back.  Two questions,
two answers:

  * **Where is the checkout named *name*?**  Beside this one.  Found by walking
    up from a file of this checkout until a directory holds ``name/name/`` with
    an ``__init__.py`` in it, which is the same walk from a clone and from a
    ``.claude/worktrees/<x>`` worktree, and always lands on the primary.  That
    is :func:`sibling_checkout`; :func:`ensure_sibling_importable` puts it on
    ``sys.path`` -- at the back, and only when nothing already answers for the
    name, so a session that chose a checkout through ``PYTHONPATH`` keeps it.
  * **Where do the suite's apps live on this machine?**  Wherever the content
    overlay says, in search order, with a fallback under the library root.  That
    is :func:`project_roots` and :func:`project_dir`, for the apps that reach a
    sibling's *files* rather than its package.

Standard library only.
"""
from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def sibling_checkout(name: str, *, near: Path) -> Path:
    """The *name* checkout beside the one *near* is in; its ``name/`` child is the package.

    Walked rather than counted: the same walk from a clone and from a worktree
    under ``.claude/worktrees``, and it lands on the primary checkout either way.
    """
    here = Path(near).resolve()
    for parent in here.parents:
        checkout = parent / name
        if (checkout / name / "__init__.py").exists():
            return checkout
    raise RuntimeError(f"Could not locate the {name} checkout above {here}")


def _really_importable(name: str) -> bool:
    """Whether *name* resolves to a package with a file behind it.

    A checkout laid out beside this one answers ``find_spec`` without being the
    package at all: the repo directory shares the package's name, so with the
    checkouts' parent on the path it resolves as an empty namespace package, and
    every submodule under it is missing.  A namespace hit is not a choice anyone
    made; a real spec is, and it is kept.
    """
    spec = importlib.util.find_spec(name)
    return spec is not None and spec.origin is not None


def ensure_sibling_importable(name: str, *, near: Path) -> None:
    """Make ``import name`` find the sibling checkout, unless something already does.

    Appended, never inserted at the front: the checkout also holds the sibling's
    own ``tests`` and ``tools`` packages, and at the front they shadow this app's.
    Skipped when *name* already resolves to a real package: a hosting session, or
    a test run, that put a particular checkout on ``PYTHONPATH`` has chosen which
    copy this app runs, and the walked-up primary must not un-choose it.
    """
    if _really_importable(name):
        return
    root = str(sibling_checkout(name, near=near))
    if root not in sys.path:
        sys.path.append(root)


def project_roots(content: Mapping[str, Any], *, fallback: Path) -> tuple[Path, ...]:
    """The folders that hold the suite's app checkouts, in search order.

    An overlay that says nothing means *fallback* -- ``<library root>/projects``,
    where the repos lived before they moved out of the file-synced tree the
    library stays in.  A *list* rather than one path so a part-finished move
    resolves: each checkout is found wherever it actually is right now, with no
    window where half the suite is unreachable.
    """
    roots = content.get("project_roots")
    if not roots:
        return (Path(fallback),)
    return tuple(Path(root) for root in roots)


def project_dir(name: str, roots: Sequence[Path]) -> Path:
    """The sibling checkout *name*, from the first root that actually holds it.

    Falls back to a path under the first root when no root does: a sibling that
    is not installed is every consumer's ordinary case -- they all guard on
    existence -- so it must not be an import-time crash.
    """
    for root in roots:
        candidate = Path(root) / name
        if candidate.is_dir():
            return candidate
    return Path(roots[0]) / name
