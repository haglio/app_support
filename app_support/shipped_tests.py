from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# A shipped file is collected beside the run's trees, as a module of the package
# it is installed in, and never handed to pytest as a path: pytest reaches a path
# it is handed by listing every folder above it, and above a venv in the temp
# folder those are every other run's folders, any of which can vanish mid-listing.


def is_a_full_run(config) -> bool:
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
