"""Checks of the repository itself run before every other test.

A check whose subject is the repository -- its tracked files, its code as a whole,
its settings -- fails on one stray line anywhere in the tree, and a fail-fast run
that reaches it last has spent its whole length on tests that could not have found
it. So such a check is marked, and every marked test leads the run::

    pytestmark = pytest.mark.repo_check

The checks this package ships carry the mark, and naming any of their plugins
brings this one with it.
"""
from __future__ import annotations

import pytest

MARK = "repo_check"


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", f"{MARK}: a check of the repository itself, run before every other test")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(items):
    yield
    items.sort(key=lambda item: item.get_closest_marker(MARK) is None)
