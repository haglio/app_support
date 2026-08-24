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
#
# One consequence: this package must never grow a `conftest.py` anywhere above
# the shipped file, because pytest loads every conftest on the path up from a
# collected one and would run it inside every consumer's session.
_SHIPPED_TESTS = str(Path(__file__).resolve().parent / "test_tracked_tree.py")


def _is_a_run_of_whole_trees(args: list[str]) -> bool:
    """Whether this session is running trees rather than chosen tests.

    A run of whole trees is one nobody has narrowed: a bare ``pytest``, whose
    arguments come from ``testpaths`` or the invocation directory, or one naming
    directories. Those are what CI runs -- every repo in this family runs a bare
    ``python -m pytest -q`` -- and they are where the guard belongs.

    A run that names a file or a node id has been narrowed on purpose, and
    enforcing there costs more than it protects. It puts a whole-tree scan in
    front of a one-test run, and it lands the guard in the middle of any test
    that shells out to pytest against a chosen file and counts what came back --
    which four repos in this family do, and which is how this rule was found.
    """
    return bool(args) and all(Path(arg.split("::")[0]).is_dir() for arg in args)


def pytest_configure(config) -> None:
    if _SHIPPED_TESTS in config.args or not _is_a_run_of_whole_trees(config.args):
        return
    config.args.append(_SHIPPED_TESTS)
