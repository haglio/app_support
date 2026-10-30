"""Where the other checkouts of the family are, asked one way.

The family's repos are cloned side by side, and an app that needs a sibling --
its shared widgets, the Funestras' core -- asked where it was in eight
independent ways, four of them by spelling the directory's name
into a path count.  Two of them put the sibling on ``sys.path`` with opposite
ideas about where: one at the front, where the sibling's own ``tests`` and
``tools`` packages then shadowed the app's, and one at the back.  Three
questions, three answers:

  * **Where is the checkout named *name*?**  Beside this one.  Found by walking
    up from a file of this checkout until a directory holds ``name/name/`` with
    an ``__init__.py`` in it, which is the same walk from a clone and from a
    ``.claude/worktrees/<x>`` worktree, and always lands on the primary.  That
    is :func:`sibling_checkout`; :func:`ensure_sibling_importable` puts it on
    ``sys.path`` -- at the back, and only when nothing already answers for the
    name, so a session that chose a checkout through ``PYTHONPATH`` keeps it.
  * **Where do the suite's apps live on this machine?**  Wherever the settings
    all of Haglio shares say, in search order, with a fallback under the library
    root.  That is :func:`app_support.haglio_settings.project_roots` and
    :func:`project_dir`, for the apps that reach a sibling's *files* rather than
    its package.
  * **Which checkouts import a package?**  The ones beside it whose tracked code
    says so, which is how a library's dead-code gate finds the apps that call it
    without naming them.  That is :func:`checkouts_that_import`.

The same question asked about *this* checkout is
:func:`assert_imported_from_checkout`, which a suite calls on itself.

Standard library only.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType

# A sibling's earlier name, and the name it has now. A checkout keeps its folder's
# old name until someone moves it, and a CI job clones under the name it spells.
RENAMED_SIBLINGS = {"player_core": "funestra"}


def names_of(sibling: str) -> tuple[str, ...]:
    return (sibling, *(old for old, new in RENAMED_SIBLINGS.items() if new == sibling))


def primary_checkout_of(checkout: Path) -> Path:
    # Imported here: the run's plugins import this module before pytest-cov starts
    # measuring, and so would be every module it imports, win32 among them.
    from app_support.subprocess_utils import hidden_subprocess_kwargs  # noqa: PLC0415

    try:
        found = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=False, **hidden_subprocess_kwargs())
    except OSError:
        return checkout
    return Path(found.stdout.strip()).parent if found.returncode == 0 else checkout


def workspace_of(module_file: Path) -> Path:
    """The folder holding the checkouts beside the one *module_file* is in, from a
    worktree of it as well."""
    checkout = primary_checkout_of(Path(module_file).resolve().parents[1])
    if not (checkout / "pyproject.toml").is_file():
        raise ValueError(
            f"{module_file} is not in a checkout, so the checkouts beside it cannot be found: "
            "name the folder that holds them with --workspace")
    return checkout.parent


def checkouts_that_import(*packages: str, near: Path) -> list[Path]:
    """The checkouts beside the one *near* is in whose tracked code imports one of
    *packages*: found rather than named, so a library never has to know its apps."""
    an_import = rf"^[[:space:]]*(from|import)[[:space:]]+({'|'.join(packages)})([.[:space:]]|$)"
    return [
        checkout for checkout in sorted(workspace_of(near).iterdir())
        if checkout.is_dir()
        and not any((checkout / package / "__init__.py").is_file() for package in packages)
        and subprocess.run(
            ["git", "-C", str(checkout), "grep", "-q", "-E", "-e", an_import, "--", "*.py"],
            capture_output=True, check=False).returncode == 0
    ]


def sibling_checkout(name: str, *, near: Path) -> Path:
    """The *name* checkout beside the one *near* is in; its ``name/`` child is the package.

    Walked rather than counted: the same walk from a clone and from a worktree
    under ``.claude/worktrees``, and it lands on the primary checkout either way.
    """
    here = Path(near).resolve()
    for parent in here.parents:
        for spelled in names_of(name):
            checkout = parent / spelled
            if (checkout / spelled / "__init__.py").exists():
                return checkout
    raise RuntimeError(f"Could not locate the {name} checkout above {here}")


def _really_importable(name: str) -> bool:
    """Whether *name* resolves to a package with a file backing it.

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


def project_roots(configured: Iterable[str | Path] | None, *, fallback: Path) -> tuple[Path, ...]:
    """The folders that hold the suite's app checkouts, in search order.

    *configured* is the ``project_roots`` setting.  Nothing there means
    *fallback*: ``<library root>/projects``, where the repos lived before they
    moved out of the file-synced tree the library stays in.  A *list* rather than one path so a
    part-finished move resolves: each checkout is found wherever it actually is
    right now, with no window where half the suite is unreachable.
    """
    roots = tuple(Path(root) for root in configured or ())
    return roots or (Path(fallback),)


def project_dir(name: str, roots: Sequence[Path]) -> Path:
    """The sibling checkout *name*, from the first root that actually holds it.

    Falls back to a path under the first root when no root does: a sibling that
    is not installed is every consumer's ordinary case -- they all guard on
    existence -- so it must not be an import-time crash.
    """
    for root in roots:
        for spelled in names_of(name):
            candidate = Path(root) / spelled
            if candidate.is_dir():
                return candidate
    return Path(roots[0]) / name


def assert_imported_from_checkout(package: ModuleType, *, checkout: Path) -> None:
    """Refuse a suite that imported *package* from somewhere other than *checkout*."""
    origin = getattr(package, "__file__", None)
    if origin is not None and Path(origin).resolve().is_relative_to(Path(checkout).resolve()):
        return
    raise RuntimeError(
        f"{package.__name__} was imported from {origin}, not from {checkout}. "
        f"Set PYTHONPATH={checkout} so the suite tests the checkout it is in."
    )
