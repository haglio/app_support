"""How tangled a repository is, as counts per file for its baseline to hold.

Most counts are of every file. A class or file enters the size counts only past
the family's limit, so ordinary growth stays free and what is already too big
cannot grow.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from app_support.coupling.classes import measure_classes
from app_support.coupling.doubles import count_doubles
from app_support.coupling.imports import ModuleTree, another_apps_imports
from app_support.gates import Checkout
from app_support.unread import python_files

METHODS_LIMIT = 30
ATTRIBUTES_LIMIT = 30
CHAIN_LENGTH_LIMIT = 3
STATEMENTS_LIMIT = 300
FAN_OUT_LIMIT = 15

_DOUBLES = ("mocks", "patches", "monkeypatches", "simple_namespaces", "library_patches")


def _sources(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    files = (found for path in paths for found in ([path] if path.is_file() else python_files(path)))
    return {file.relative_to(root).as_posix(): file.read_text(encoding="utf-8") for file in files}


def _none_at_zero(counted: Mapping[str, int]) -> dict[str, int]:
    return {key: count for key, count in counted.items() if count}


def _over(limit: int, counted: Mapping[str, int]) -> dict[str, int]:
    return {key: count for key, count in counted.items() if count > limit}


def _statements(source: str) -> int:
    return sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(source)))


@lru_cache(maxsize=1)
def _measured(code_files: tuple[tuple[str, str], ...], test_files: tuple[tuple[str, str], ...],
              own: tuple[str, ...]) -> dict[str, dict[str, int]]:
    code = dict(code_files)
    tree = ModuleTree(code)
    classes = {path: measure_classes(source) for path, source in code.items()}
    surfaces = {f"{path}::{name}": surface for path, found in classes.items() for name, surface in found.items()}
    doubles = {path: asdict(count_doubles(source, own=own)) for path, source in test_files}
    return {
        "reach_chains": _none_at_zero({path: sum(surface.chains for surface in found.values())
                                       for path, found in classes.items()}),
        "mutables_imported": tree.mutables_imported(),
        **{name: _none_at_zero({path: counts[name] for path, counts in doubles.items()}) for name in _DOUBLES},
        "methods": _over(METHODS_LIMIT, {unit: surface.methods for unit, surface in surfaces.items()}),
        "class_attributes": _over(ATTRIBUTES_LIMIT, {unit: surface.attributes for unit, surface in surfaces.items()}),
        "chain_length": _over(CHAIN_LENGTH_LIMIT, {unit: surface.longest_chain for unit, surface in surfaces.items()}),
        "statements": _over(STATEMENTS_LIMIT, {path: _statements(source) for path, source in code.items()}),
        "fan_out": _over(FAN_OUT_LIMIT, tree.fan_out()),
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
