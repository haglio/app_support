"""How tangled a repository is, per file and per class; ``app_support.gates.baseline`` holds the numbers."""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app_support.coupling.classes import ClassSurface, measure_classes
from app_support.coupling.doubles import count_doubles
from app_support.coupling.imports import ModuleTree, another_apps_imports
from app_support.gates import Checkout
from app_support.unread import python_files

CLASS_LIMITS = {"methods": 30, "attributes": 30, "chains": 30, "chain-length": 3}
FILE_LIMITS = {"statements": 300, "fan-out": 15}


@dataclass(frozen=True)
class Measured:
    per_file: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    over_the_limits: Mapping[str, int] = field(default_factory=dict)
    another_apps_imports: Mapping[str, int] = field(default_factory=dict)


def _sources(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    files = (found for path in paths for found in ([path] if path.is_file() else python_files(path)))
    return {file.relative_to(root).as_posix(): file.read_text(encoding="utf-8") for file in files}


def _over(limits: Mapping[str, int], unit: str, measures: Mapping[str, int]) -> Iterator[tuple[str, int]]:
    for name, count in measures.items():
        if count > limits[name]:
            yield f"{unit}::{name}", count


def _classes_over(classes: Mapping[str, ClassSurface]) -> Iterator[tuple[str, int]]:
    for unit, surface in classes.items():
        yield from _over(CLASS_LIMITS, unit, {"methods": surface.methods, "attributes": surface.attributes,
                                              "chains": surface.chains, "chain-length": surface.longest_chain})


def _statements(source: str) -> int:
    return sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(source)))


def _files_over(code: Mapping[str, str], fan_out: Mapping[str, int]) -> Iterator[tuple[str, int]]:
    for path, source in code.items():
        yield from _over(FILE_LIMITS, path, {"statements": _statements(source), "fan-out": fan_out[path]})


def _kept(counts: Mapping[str, int]) -> dict[str, int]:
    return {unit: count for unit, count in counts.items() if count}


def measure(checkout: Checkout) -> Measured:
    code = _sources(checkout.root, checkout.code)
    tests = _sources(checkout.root, checkout.own_tests)
    tree = ModuleTree(code)
    surfaces = {path: measure_classes(source) for path, source in code.items()}
    classes = {f"{path}::{name}": surface for path, held in surfaces.items() for name, surface in held.items()}
    doubles = {path: asdict(count_doubles(source, own=checkout.own_names)) for path, source in tests.items()}
    return Measured(
        per_file={
            "reach_chains": _kept({path: sum(surface.chains for surface in held.values())
                                   for path, held in surfaces.items()}),
            "mutables_imported": _kept(tree.mutables_imported()),
            **{name: _kept({path: counts[name] for path, counts in doubles.items()})
               for name in ("mocks", "patches", "monkeypatches", "simple_namespaces", "library_patches")},
        },
        over_the_limits=dict((*_classes_over(classes), *_files_over(code, tree.fan_out()))),
        another_apps_imports=another_apps_imports({**code, **tests}, own=checkout.own_names),
    )


def assert_no_app_imports_another(measured: Measured) -> None:
    assert not measured.another_apps_imports, (
        "an app reaches another through the files and sockets they share, never its code: "
        + ", ".join(f"{path} imports another app" for path in sorted(measured.another_apps_imports)))
