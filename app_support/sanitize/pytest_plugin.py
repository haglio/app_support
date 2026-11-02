from __future__ import annotations

from pathlib import Path

from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_SHIPPED_TESTS = Path(__file__).resolve().parent / "test_tracked_tree.py"


def pytest_configure(config) -> None:
    ship(config, _SHIPPED_TESTS)
