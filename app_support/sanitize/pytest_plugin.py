"""Give a repository the guard's enforcement check by asking for it once.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.sanitize.pytest_plugin"

The unit tests of the guard itself belong here, once, and are not a consumer's
business. What every checkout does need is the check whose subject is *that*
checkout: no tracked file may carry a blocklisted term. ``app_support.shipped_tests``
says how that check reaches the consumer's session.
"""
from __future__ import annotations

from pathlib import Path

from app_support.shipped_tests import ship

pytest_plugins = ["app_support.repo_checks"]

_SHIPPED_TESTS = Path(__file__).resolve().parent / "test_tracked_tree.py"


def pytest_configure(config) -> None:
    ship(config, _SHIPPED_TESTS, called="the blocked-word check")
