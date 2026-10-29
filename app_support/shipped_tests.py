"""Give a repository a check whose subject is that repository, by its naming a plugin once.

    # pyproject.toml
    [tool.pytest.ini_options]
    addopts = "-p app_support.sanitize.pytest_plugin"

Each such check was a copied test module in eleven repos, which is how one of
them lost four cases without anyone noticing.

Deliberately not a ``pytest11`` entry point. An auto-loading plugin would add a
test to every suite in any venv that happens to have this package installed,
which is most of them -- so adoption would be something that happened to a repo
rather than something it asked for, and there would be no way to roll it out one
repo at a time.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_THE_RUN_AS_ASKED = pytest.StashKey[list[str]]()

# A shipped file is put into the session's arguments rather than collected off
# disk: it lives wherever this package was installed, nowhere near the tree pytest
# walks. What collecting it from there reaches in a consumer's session -- its
# `sys.path`, and every conftest above the file -- `tests/test_shipped_tests.py`
# holds down.


def is_a_run_of_whole_trees(args: list[str]) -> bool:
    """Whether this session is running trees rather than chosen tests.

    A run of whole trees is one nobody has narrowed: a bare ``pytest``, whose
    arguments pytest fills in from ``testpaths`` or the invocation directory as
    absolute paths, or one naming directories. Those are what CI runs -- every
    repo in this family runs a bare ``python -m pytest -q`` -- and they are where
    a shipped check belongs.

    A run that names a file or a node id has been narrowed on purpose, and
    enforcing there costs more than it protects. It puts a whole-tree check in
    front of a one-test run, and it lands the check in the middle of any test
    that shells out to pytest against a chosen file and counts what came back --
    which four repos in this family do, and which is how this rule was found.
    """
    return bool(args) and all(Path(arg).is_dir() for arg in args)


def ship(config, shipped: Path) -> None:
    asked = config.stash.setdefault(_THE_RUN_AS_ASKED, list(config.args))
    test_file = str(shipped)
    if test_file in config.args or not is_a_run_of_whole_trees(asked):
        return
    config.args.insert(0, test_file)
