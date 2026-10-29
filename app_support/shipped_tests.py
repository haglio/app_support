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

A check handed to a run of whole trees is held to being in it. pytest fails
nothing over a file it never collected and counts it nowhere, so a check that
drops out of a run reads exactly like one that passed; a run that loses one ends
before any test runs, with an error naming it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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


def ship(config, shipped: Path, *, called: str) -> None:
    handed = _ChecksHandedToTheRun.of(config)
    handed.names[shipped] = called
    test_file = str(shipped)
    if test_file in config.args or not is_a_run_of_whole_trees(handed.run_as_asked):
        return
    config.args.insert(0, test_file)


class _ChecksHandedToTheRun:
    _KEY = pytest.StashKey["_ChecksHandedToTheRun"]()
    _NAME = "app_support.shipped_tests.handed"

    def __init__(self, run_as_asked: list[str]):
        self.run_as_asked = run_as_asked
        self.names: dict[Path, str] = {}
        self._deselected: set[pytest.Item] = set()

    @classmethod
    def of(cls, config) -> _ChecksHandedToTheRun:
        if (handed := config.stash.get(cls._KEY, None)) is None:
            handed = config.stash[cls._KEY] = cls(list(config.args))
            config.pluginmanager.register(handed, cls._NAME)
        return handed

    def pytest_deselected(self, items) -> None:
        self._deselected.update(items)

    @pytest.hookimpl(wrapper=True, trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        """The innermost wrapper, so a run dealt into parts is held to what it collected:
        pytest-test-groups, which deals the family gate's parts, splits the run in a
        wrapper outside this one and reports none of what it leaves to the other parts."""
        collected = {item: shipped for item in items
                     if (shipped := self._shipped_file_of(item)) is not None}
        if self._owes_every_check(config):
            self._refuse_the_run(without=sorted(set(self.names) - set(collected.values())),
                                 because="handed to this run and never collected")
        yield
        kept = set(items) | self._deselected
        self._refuse_the_run(
            without=sorted({shipped for item, shipped in collected.items() if item not in kept}),
            because="collected and then dropped from this run without being deselected")

    def _owes_every_check(self, config) -> bool:
        """Not a run of only the last failures: pytest's cache plugin leaves every file
        without a recorded failure uncollected then, and reports none of them."""
        return is_a_run_of_whole_trees(self.run_as_asked) and not config.getoption("lf", False)

    def _shipped_file_of(self, item) -> Path | None:
        return next((shipped for shipped in self.names
                     if item.path.name == shipped.name
                     and item.path.resolve() == shipped.resolve()), None)

    def _refuse_the_run(self, without: list[Path], because: str) -> None:
        if without:
            raise pytest.UsageError(*(
                f"{because}: {self.names[shipped]} ({shipped}). "
                "A run cannot pass without every check it is handed."
                for shipped in without))
