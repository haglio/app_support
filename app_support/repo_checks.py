from __future__ import annotations

import pytest

MARK = "repo_check"


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", f"{MARK}: a check of the repository itself, run before every other test")
    # Imported here rather than through pytest_plugins: a plugin named with -p is imported before
    # pytest-cov starts measuring, and so would be every module it imports.
    config.pluginmanager.import_plugin("app_support.stopped_runs")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(items):
    yield
    items.sort(key=lambda item: item.get_closest_marker(MARK) is None)
