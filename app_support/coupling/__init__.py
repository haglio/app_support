from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from app_support.coupling.imports import ModuleTree, another_apps_imports
from app_support.coupling.library_patches import library_patches_in
from app_support.gates import Checkout
from app_support.unread import python_files


def _sources(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    files = (found for path in paths for found in ([path] if path.is_file() else python_files(path)))
    return {file.relative_to(root).as_posix(): file.read_text(encoding="utf-8") for file in files}


@lru_cache(maxsize=1)
def _measured(code_files: tuple[tuple[str, str], ...], test_files: tuple[tuple[str, str], ...],
              own: tuple[str, ...]) -> dict[str, dict[str, int]]:
    patched = {path: library_patches_in(source, own=own) for path, source in test_files}
    return {
        "mutables_imported": ModuleTree(dict(code_files)).mutables_imported(),
        "library_patches": {path: count for path, count in patched.items() if count},
    }


def measured_sections(checkout: Checkout) -> dict[str, dict[str, int]]:
    return _measured(tuple(_sources(checkout.root, checkout.code).items()),
                     tuple(_sources(checkout.root, checkout.own_tests).items()), checkout.own_names)


def assert_no_app_imports_another(checkout: Checkout) -> None:
    found = another_apps_imports(
        {**_sources(checkout.root, checkout.code), **_sources(checkout.root, checkout.own_tests)},
        own=checkout.own_names)
    assert not found, (
        "an app reaches another through the files and sockets they share, never its code: "
        + ", ".join(f"{path} imports another app" for path in sorted(found)))
