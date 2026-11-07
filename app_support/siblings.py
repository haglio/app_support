from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType

RENAMED_SIBLINGS = {"player_core": "funestra"}


def not_a_checkout(folder_name: str) -> bool:
    return folder_name.startswith(".")


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
    checkout = primary_checkout_of(Path(module_file).resolve().parents[1])
    if not (checkout / "pyproject.toml").is_file():
        raise ValueError(
            f"{module_file} is not in a checkout, so the checkouts beside it cannot be found: "
            "name the folder that holds them with --workspace")
    return checkout.parent


def checkouts_that_import(*packages: str, near: Path) -> list[Path]:
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
    here = Path(near).resolve()
    for parent in here.parents:
        for spelled in names_of(name):
            checkout = parent / spelled
            if (checkout / spelled / "__init__.py").exists():
                return checkout
    raise RuntimeError(f"Could not locate the {name} checkout above {here}")


def _really_importable(name: str) -> bool:
    spec = importlib.util.find_spec(name)
    return spec is not None and spec.origin is not None


def ensure_sibling_importable(name: str, *, near: Path) -> None:
    if _really_importable(name):
        return
    root = str(sibling_checkout(name, near=near))
    if root not in sys.path:
        sys.path.append(root)


def project_roots(configured: Iterable[str | Path] | None, *, fallback: Path) -> tuple[Path, ...]:
    roots = tuple(Path(root) for root in configured or ())
    return roots or (Path(fallback),)


def project_dir(name: str, roots: Sequence[Path]) -> Path:
    for root in roots:
        for spelled in names_of(name):
            candidate = Path(root) / spelled
            if candidate.is_dir():
                return candidate
    return Path(roots[0]) / name


def assert_imported_from_checkout(package: ModuleType, *, checkout: Path) -> None:
    origin = getattr(package, "__file__", None)
    if origin is not None and Path(origin).resolve().is_relative_to(Path(checkout).resolve()):
        return
    raise RuntimeError(
        f"{package.__name__} was imported from {origin}, not from {checkout}. "
        f"Set PYTHONPATH={checkout} so the suite tests the checkout it is in."
    )
