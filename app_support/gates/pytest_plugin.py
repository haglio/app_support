from __future__ import annotations

from pathlib import Path

from app_support.gates import Checkout
from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_HERE = Path(__file__).resolve().parent
_EVERY_REPOSITORYS = ("test_clocks.py", "test_coupling.py", "test_dead_code.py", "test_dependencies.py", "test_lint.py",
                      "test_launchers.py", "test_quality_baseline.py")


def pytest_configure(config) -> None:
    for gate in _EVERY_REPOSITORYS:
        ship(config, _HERE / gate)
    if config.pluginmanager.has_plugin("app_support.coverage_gate"):
        ship(config, _HERE / "test_coverage.py")
    checkout = Checkout(Path(config.inipath).parent) if config.inipath else None
    if checkout and checkout.is_a_library:
        ship(config, _HERE / "test_a_shared_package.py")
