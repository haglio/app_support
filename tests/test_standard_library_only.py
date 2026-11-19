from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "app_support"

_THE_CHECKS_PYTEST_COLLECTS = frozenset({
    "sanitize/test_tracked_tree.py", "processor_places.py", "repo_checks.py", "shipped_tests.py",
    "worker_processes.py",
})
_READS_COVERAGES_OWN_PATTERN = "coverage_gate.py"


def _imported_from_outside_the_standard_library(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names - set(sys.stdlib_module_names) - {"app_support"}


def _allowed(module: str) -> set[str]:
    if module == _READS_COVERAGES_OWN_PATTERN:
        return {"pytest", "coverage"}
    if module in _THE_CHECKS_PYTEST_COLLECTS or module.startswith("gates/test_"):
        return {"pytest"}
    return set()


def _modules() -> dict[str, set[str]]:
    return {path.relative_to(PACKAGE).as_posix(): _imported_from_outside_the_standard_library(path)
            for path in sorted(PACKAGE.rglob("*.py"))}


def test_every_module_imports_only_the_standard_library_and_a_plugin_its_pytest():
    outside = {module: sorted(names - _allowed(module)) for module, names in _modules().items()
               if names - _allowed(module)}

    assert outside == {}, "installed into every app's venv, so a dependency here is a dependency everywhere"


def test_a_plugin_that_stopped_reaching_for_pytest_comes_off_the_list():
    unused = {module: sorted(_allowed(module) - names) for module, names in _modules().items()
              if _allowed(module) - names}

    assert unused == {}
