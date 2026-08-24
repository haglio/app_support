"""Give a repository the guard's enforcement check by asking for it once.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.sanitize.pytest_plugin"

The unit tests of the guard itself belong here, once, and are not a consumer's
business. What every checkout does need is the check whose subject is *that*
checkout: no tracked file may carry a blocklisted term. It was a copied test
module in eleven repos, which is how one of them lost four cases without anyone
noticing.

Deliberately not a ``pytest11`` entry point. An auto-loading plugin would add a
test to every suite in any venv that happens to have this package installed,
which is most of them -- so adoption would be something that happened to a repo
rather than something it asked for, and there would be no way to roll it out one
repo at a time.
"""
from __future__ import annotations

from pathlib import Path

# Appended to the session's arguments rather than collected off disk: the file
# lives in site-packages, nowhere near the tree pytest walks. It sits inside a
# package all the way up, so pytest imports it under its dotted name and leaves
# `sys.path` alone -- a loose module would put this directory on the front of it
# and shadow whatever the consumer calls its own top-level modules.
_SHIPPED_TESTS = str(Path(__file__).resolve().parent / "test_tracked_tree.py")


def pytest_configure(config) -> None:
    if _SHIPPED_TESTS not in config.args:
        config.args.append(_SHIPPED_TESTS)
