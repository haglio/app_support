"""Give a repository the family's gates by asking for them once.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.gates.pytest_plugin --timeout=60 --timeout-method=thread"

Every repository gets the clocks, the dead-code, dependency, lint and launcher
checks; one that names ``app_support.coverage_gate`` gets the check of its
coverage config too, and a package every app installs gets the check of its
version. ``app_support.shipped_tests`` says how they reach the run.
"""
from __future__ import annotations

from pathlib import Path

from app_support.gates import Checkout
from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_HERE = Path(__file__).resolve().parent
_EVERY_REPOSITORYS = ("test_clocks.py", "test_dead_code.py", "test_dependencies.py", "test_lint.py",
                      "test_launchers.py")


def pytest_configure(config) -> None:
    for gate in _EVERY_REPOSITORYS:
        ship(config, _HERE / gate)
    if config.pluginmanager.has_plugin("app_support.coverage_gate"):
        ship(config, _HERE / "test_coverage.py")
    if config.inipath and Checkout(Path(config.inipath).parent).is_a_library:
        ship(config, _HERE / "test_a_shared_package.py")
