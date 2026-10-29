"""Give a repository the clock checks by asking for them once.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.clocks.pytest_plugin --timeout=60 --timeout-method=thread"

``app_support.shipped_tests`` says how the checks reach the consumer's session.
"""
from __future__ import annotations

from pathlib import Path

from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_SHIPPED_TESTS = Path(__file__).resolve().parent / "test_clocks.py"


def pytest_configure(config) -> None:
    ship(config, _SHIPPED_TESTS)
