"""How tangled a repository is, as counts that only come down.

A repository pins what it measures under ``[tool.haglio.coupling]`` in its
pyproject: a ceiling for each count over its whole tree, and under ``held`` a
ceiling for each class or file past one of the family's limits. A count that
rises fails the run, and so does one that falls with its ceiling left standing,
so what was cleaned stays clean.
"""
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
LIMITS = {**CLASS_LIMITS, **FILE_LIMITS}


@dataclass(frozen=True)
class Measured:
    totals: Mapping[str, int] = field(default_factory=dict)
    over_the_limits: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    another_apps_imports: Mapping[str, int] = field(default_factory=dict)


def _sources(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    files = (found for path in paths for found in ([path] if path.is_file() else python_files(path)))
    return {file.relative_to(root).as_posix(): file.read_text(encoding="utf-8") for file in files}


def _over(limits: Mapping[str, int], measures: Mapping[str, int]) -> dict[str, int]:
    return {name: count for name, count in measures.items() if count > limits[name]}


def _classes_over(classes: Mapping[str, ClassSurface]) -> Iterator[tuple[str, dict[str, int]]]:
    for unit, surface in classes.items():
        yield unit, _over(CLASS_LIMITS, {"methods": surface.methods, "attributes": surface.attributes,
                                         "chains": surface.chains, "chain-length": surface.longest_chain})


def _statements(source: str) -> int:
    return sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(source)))


def _files_over(code: Mapping[str, str], fan_out: Mapping[str, int]) -> Iterator[tuple[str, dict[str, int]]]:
    for path, source in code.items():
        yield path, _over(FILE_LIMITS, {"statements": _statements(source), "fan-out": fan_out[path]})


def measure(checkout: Checkout) -> Measured:
    code = _sources(checkout.root, checkout.code)
    tests = _sources(checkout.root, checkout.own_tests)
    tree = ModuleTree(code)
    classes = {f"{path}::{name}": surface for path, source in code.items()
               for name, surface in measure_classes(source).items()}
    doubles = [asdict(count_doubles(source, own=checkout.own_names)) for source in tests.values()]
    return Measured(
        totals={
            "reach-chains": sum(surface.chains for surface in classes.values()),
            "mutables-imported": sum(tree.mutables_imported().values()),
            **{name.replace("_", "-"): sum(counts[name] for counts in doubles)
               for name in ("mocks", "patches", "monkeypatches", "simple_namespaces", "library_patches")},
        },
        over_the_limits={unit: over for unit, over in (*_classes_over(classes), *_files_over(code, tree.fan_out()))
                         if over},
        another_apps_imports=another_apps_imports({**code, **tests}, own=checkout.own_names),
    )


def _total_problems(totals: Mapping[str, int], ceilings: Mapping) -> Iterator[str]:
    for name, count in sorted(totals.items()):
        ceiling = ceilings.get(name, 0)
        if count > ceiling:
            yield f"{name} rose to {count}, over its ceiling of {ceiling}"
        elif count < ceiling:
            yield f"{name} fell to {count}: lower its ceiling from {ceiling} to {count}"


def _held_problems(over: Mapping[str, Mapping[str, int]], held: Mapping) -> Iterator[str]:
    for unit in sorted({*over, *held}):
        measures, ceilings = over.get(unit, {}), held.get(unit, {})
        for name in sorted({*measures, *ceilings}):
            count, ceiling = measures.get(name), ceilings.get(name)
            if count is None:
                yield f"{unit} is within the family's limit for {name}: take it off [tool.haglio.coupling.held]"
            elif ceiling is None:
                yield f"{unit} has {count} {name}, over the family's limit of {LIMITS[name]}"
            elif count > ceiling:
                yield f"{unit} rose to {count} {name}, over its ceiling of {ceiling}"
            elif count < ceiling:
                yield f"{unit} fell to {count} {name}: lower its ceiling from {ceiling} to {count}"


def assert_within_ceilings(measured: Measured, ceilings: Mapping) -> None:
    problems = [*_total_problems(measured.totals, ceilings),
                *_held_problems(measured.over_the_limits, ceilings.get("held", {}))]
    assert not problems, (
        "the repo's [tool.haglio.coupling] holds these where they stood; a ceiling only comes down, "
        "so a rise is cut back rather than pinned:\n" + "\n".join(problems))


def assert_no_app_imports_another(measured: Measured) -> None:
    assert not measured.another_apps_imports, (
        "an app reaches another through the files and sockets they share, never its code: "
        + ", ".join(f"{path} imports another app" for path in sorted(measured.another_apps_imports)))
