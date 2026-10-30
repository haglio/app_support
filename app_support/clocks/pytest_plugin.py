"""The clock checks alone, for a repository that has not yet asked for every family gate.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.clocks.pytest_plugin --timeout=60 --timeout-method=thread"

``app_support.gates.pytest_plugin`` ships the same checks with the rest, and a
run that names both collects them once.
"""
from __future__ import annotations

from pathlib import Path

import app_support.gates
from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_SHIPPED_TESTS = Path(app_support.gates.__file__).resolve().parent / "test_clocks.py"


def pytest_configure(config) -> None:
    ship(config, _SHIPPED_TESTS)
