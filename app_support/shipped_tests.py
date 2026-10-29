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

# A shipped file is collected beside the run's trees, as a module of the package
# it is installed in, and never handed to pytest as a path: pytest reaches a path
# it is handed by listing every folder above it, and above a venv in the temp
# folder those are every other run's folders, any of which can vanish mid-listing.


def is_a_run_of_whole_trees(args: list[str]) -> bool:
    """Whether this session is running trees rather than chosen tests.

    A run of whole trees is one nobody has narrowed: a bare ``pytest``, whose
    arguments pytest fills in from ``testpaths`` or the invocation directory, or
    one naming directories. Those are what CI runs -- every repo in this family
    runs a bare ``python -m pytest -q`` -- and they are where a shipped check
    belongs.

    A run that names a file or a node id has been narrowed on purpose, and
    enforcing there costs more than it protects. It puts a whole-tree check in
    front of a one-test run, and it lands the check in the middle of any test
    that shells out to pytest against a chosen file and counts what came back --
    which four repos in this family do, and which is how this rule was found.
    """
    return bool(args) and all(Path(arg).is_dir() for arg in args)


_SHIPPED = pytest.StashKey[dict[Path, None]]()


def ship(config, shipped: Path) -> None:
    if _SHIPPED not in config.stash:
        config.stash[_SHIPPED] = {}
        config.pluginmanager.register(_CollectingBesideTheTrees(), "app_support.shipped_tests")
    config.stash[_SHIPPED][shipped] = None


def collected_beside_the_trees(config) -> list[Path]:
    return list(config.stash.get(_SHIPPED, {})) if is_a_run_of_whole_trees(config.args) else []


class _CollectingBesideTheTrees:
    @pytest.hookimpl(wrapper=True)
    def pytest_make_collect_report(self, collector):
        report = yield
        if isinstance(collector, pytest.Session) and report.passed:
            report.result[:0] = [pytest.Module.from_parent(collector, path=shipped)
                                 for shipped in collected_beside_the_trees(collector.config)]
        return report

    def pytest_ignore_collect(self, collection_path, config) -> bool | None:
        return collection_path in config.stash[_SHIPPED] or None
