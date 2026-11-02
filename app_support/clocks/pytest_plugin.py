from __future__ import annotations

from pathlib import Path

import app_support.gates
from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_SHIPPED_TESTS = Path(app_support.gates.__file__).resolve().parent / "test_clocks.py"


def pytest_configure(config) -> None:
    ship(config, _SHIPPED_TESTS)
