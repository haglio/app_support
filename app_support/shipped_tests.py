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

import importlib
from pathlib import Path

import pytest

# A shipped file is collected beside the run's trees, as a module of the package
# it is installed in, and never handed to pytest as a path: pytest reaches a path
# it is handed by listing every folder above it, and above a venv in the temp
# folder those are every other run's folders, any of which can vanish mid-listing.


def is_a_full_run(config) -> bool:
    """Whether this session was started on whole trees rather than chosen tests.

    Asked of pytest's first reading of the run's own command line, never of the
    list of what the run will collect, which any plugin may name a file in first;
    for a run started on paths, ``config.option`` holds that very list.

    A run that names a file or a node id has been narrowed on purpose, and
    enforcing there costs more than it protects. It puts a whole-tree check in
    front of a one-test run, and it lands the check in the middle of any test
    that shells out to pytest against a chosen file and counts what came back --
    which four repos in this family do, and which is how this rule was found.
    """
    return all((config.invocation_params.dir / named).is_dir()
               for named in config.known_args_namespace.file_or_dir)


_SHIPPED = pytest.StashKey[dict[Path, None]]()
_FOLDER_HOLDING_THIS_PACKAGE = Path(__file__).resolve().parents[1]


def ship(config, shipped: Path) -> None:
    if _SHIPPED not in config.stash:
        config.stash[_SHIPPED] = {}
        config.pluginmanager.register(_CollectingBesideTheTrees(), "app_support.shipped_tests")
    config.stash[_SHIPPED][shipped] = None


def collected_beside_the_trees(config) -> list[Path]:
    return list(config.stash.get(_SHIPPED, {})) if is_a_full_run(config) else []


class _CollectingBesideTheTrees:
    @pytest.hookimpl(wrapper=True)
    def pytest_make_collect_report(self, collector):
        report = yield
        if isinstance(collector, pytest.Session) and report.passed:
            report.result[:0] = [_ImportedByName.from_parent(collector, path=shipped)
                                 for shipped in collected_beside_the_trees(collector.config)]
        return report

    def pytest_ignore_collect(self, collection_path, config) -> bool | None:
        return collection_path in config.stash[_SHIPPED] or None


class _ImportedByName(pytest.Module):
    def _getobj(self):
        name = self.path.relative_to(_FOLDER_HOLDING_THIS_PACKAGE).with_suffix("")
        return importlib.import_module(".".join(name.parts))
