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
# lives wherever this package was installed, nowhere near the tree pytest walks.
#
# Two things follow, and both reach into the consumer's session.
#
# Collecting a file puts the root of the package holding it at the FRONT of
# `sys.path` -- measured: this package's own repo root under an editable install,
# site-packages under a wheel. So every top-level name that directory publishes
# is offered to the consumer ahead of its own. Today it publishes exactly one,
# `app_support`, because nothing else beside it is a package; a directory without
# an `__init__.py` is only a namespace portion and loses to a real package of the
# same name. `tests/test_sanitize_plugin.py` holds that true, since the day this
# repo grows a `tests/__init__.py` is the day ten other suites import the wrong
# `tests`.
#
# And pytest loads every conftest on the path up from a collected file, so a
# `conftest.py` added anywhere above this one would run inside every consumer's
# session. Also held true by a test.
_SHIPPED_TESTS = str(Path(__file__).resolve().parent / "test_tracked_tree.py")


def _names_a_whole_tree(arg: str, rootpath: Path) -> bool:
    """Whether one session argument is a directory rather than a chosen test.

    Resolved against the working directory *and* the root directory, because the
    two kinds of argument are anchored differently: one typed on the command line
    is relative to where it was typed, while one that came from ``testpaths`` is
    relative to the root. Checking only the first made ``cd tests && pytest``
    look like a narrowed run and skip the guard -- silently, which is the one
    failure this whole check exists to not have.
    """
    target = arg.split("::")[0]
    return Path(target).is_dir() or (rootpath / target).is_dir()


def _is_a_run_of_whole_trees(args: list[str], rootpath: Path) -> bool:
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
    return bool(args) and all(_names_a_whole_tree(arg, rootpath) for arg in args)


def pytest_configure(config) -> None:
    if _SHIPPED_TESTS in config.args:
        return
    if not _is_a_run_of_whole_trees(config.args, Path(config.rootpath)):
        return
    config.args.append(_SHIPPED_TESTS)
