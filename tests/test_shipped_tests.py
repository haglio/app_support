"""Tests for how a check this package ships reaches a consumer's session."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pytest
from consumer_runs import run_pytest_in

from app_support import shipped_tests

APP_SUPPORT = Path(__file__).resolve().parents[1]
SHIPPED = sorted((APP_SUPPORT / "app_support").rglob("test_*.py"))

FAMILY_OPTIONS = ("-p no:cacheprovider -p app_support.sanitize.pytest_plugin"
                  " -p app_support.clocks.pytest_plugin")
THE_BLOCKED_WORD_CHECK = "test_no_blocklisted_terms_in_the_tracked_tree"
A_CONFTEST_THAT_LEAVES_A_MARK = """\
from pathlib import Path

Path(__file__).with_name("ran").touch()
"""
ANOTHER_RUN_CLEARING_AWAY_ITS_FOLDER_AS_THIS_ONE_COLLECTS = """\
import shutil


def pytest_collect_directory(path):
    if path.name == "another-runs-folder":
        shutil.rmtree(path)
"""
A_PLUGIN_THAT_SHUFFLES_THE_RUN = """\
from random import Random


def pytest_collection_modifyitems(items):
    Random(3).shuffle(items)
"""
A_PLUGIN_THAT_DEALS_THE_RUN_INTO_TWO_PARTS_THE_WAY_PYTEST_TEST_GROUPS_DOES = """\
from random import Random

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items):
    yield
    collected = items[:]
    Random(7).shuffle(items)
    items[:] = items[{part} - 1::2]
    items.sort(key=collected.index)
"""
A_TEST_OF_WHICH_COPY_OF_THE_REPOS_PACKAGE_IT_IMPORTS = """\
def test_the_checkouts_own_copy():
    import example_app

    assert example_app.COPY == "the checkout's"
"""


def a_consumer(tmp_path: Path) -> Path:
    repo = tmp_path / "family" / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        f'[tool.pytest.ini_options]\naddopts = "{FAMILY_OPTIONS}"\ntestpaths = ["tests"]\n',
        encoding="utf-8")
    (repo / "tests" / "test_code.py").write_text("def test_the_repos_own():\n    pass\n",
                                                 encoding="utf-8")
    return repo


def installed_at(site: Path) -> Path:
    shutil.copytree(APP_SUPPORT / "app_support", site / "app_support",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return site


class TestWhichRunsAreEnforced:
    """The rule itself, without a subprocess in the way.

    The end-to-end cases beside each plugin prove the rule reaches a real
    session; these prove which way each shape of argument is decided, including
    the ones a real session cannot easily be talked into producing.
    """

    class _Config:
        def __init__(self, args, *, started_with=()):
            self.args = list(args)
            self.known_args_namespace = argparse.Namespace(file_or_dir=list(started_with))
            self.invocation_params = pytest.Config.InvocationParams(
                args=tuple(started_with), plugins=None, dir=APP_SUPPORT)
            self.stash = pytest.Stash()
            self.pluginmanager = pytest.PytestPluginManager()

    def _is_a_full_run(self, *started_with: str) -> bool:
        return shipped_tests.is_a_full_run(self._Config([], started_with=started_with))

    def test_a_run_started_with_nothing_named_is_a_full_run(self):
        assert self._is_a_full_run()

    def test_a_run_started_on_directories_is_a_full_run(self):
        assert self._is_a_full_run("tests", str(APP_SUPPORT / "app_support"))

    def test_one_named_file_among_directories_narrows_the_whole_run(self):
        assert not self._is_a_full_run("tests", str(Path("tests") / "test_cli.py"))

    def test_a_node_id_narrows_the_run(self):
        assert not self._is_a_full_run(f"{Path('tests') / 'test_cli.py'}::test_one")

    def test_a_test_file_other_code_has_already_named_in_the_run_leaves_it_full(self):
        """The list of what a run will collect is anyone's to add to: the clock
        checks once named their file there first, and the blocked-word check,
        reading the list, took every run for a narrowed one and left itself out."""
        config = self._Config([str(APP_SUPPORT / "tests"), str(SHIPPED[1])])

        shipped_tests.ship(config, SHIPPED[0])

        assert shipped_tests.collected_beside_the_trees(config) == [SHIPPED[0]]

    def test_a_check_is_collected_once_however_often_it_is_shipped(self):
        config = self._Config([str(APP_SUPPORT / "tests")])

        shipped_tests.ship(config, SHIPPED[0])
        shipped_tests.ship(config, SHIPPED[0])

        assert shipped_tests.collected_beside_the_trees(config) == [SHIPPED[0]]

    def test_a_check_shipped_after_another_still_reaches_the_run(self):
        config = self._Config([str(APP_SUPPORT / "tests")])

        shipped_tests.ship(config, SHIPPED[0])
        shipped_tests.ship(config, SHIPPED[1])

        assert shipped_tests.collected_beside_the_trees(config) == SHIPPED[:2]

    def test_a_narrowed_run_collects_no_check_beside_what_it_named(self):
        named = str(APP_SUPPORT / "tests" / "test_cli.py")
        config = self._Config([named], started_with=[named])

        shipped_tests.ship(config, SHIPPED[0])

        assert shipped_tests.collected_beside_the_trees(config) == []


class TestWhatShippingReachesInAConsumer:
    def test_this_repo_root_offers_a_consumer_only_the_one_name(self):
        """An editable install puts this repo's root on the `sys.path` of every
        venv holding it, and a real package anywhere on the path beats a
        namespace portion of the same name wherever that sits. So every package
        that directory publishes can stand in for a directory of ten other
        suites, and `tools` and `tests` are names every one of them uses.

        It publishes only `app_support` today because nothing else beside it
        carries an `__init__.py`, so the rest are namespace portions themselves.
        That is load-bearing and invisible, so it is pinned here: the day this
        repo grows a `tests/__init__.py` is the day ten suites import the wrong
        `tests`.
        """
        published = sorted(
            entry.name for entry in APP_SUPPORT.iterdir()
            if (entry.is_dir() and (entry / "__init__.py").exists())
            or (entry.suffix == ".py" and entry.is_file())
        )

        assert published == ["app_support"], published

    def test_a_conftest_beside_the_installed_package_never_runs_in_a_consumers_session(
        self, tmp_path: Path,
    ):
        site = installed_at(tmp_path / "temp" / "venv" / "Lib" / "site-packages")
        beside = [site, site / "app_support", site / "app_support" / "sanitize"]
        for folder in beside:
            (folder / "conftest.py").write_text(A_CONFTEST_THAT_LEAVES_A_MARK, encoding="utf-8")

        done = run_pytest_in(a_consumer(tmp_path), "--collect-only", app_support_from=site)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert THE_BLOCKED_WORD_CHECK in done.stdout, done.stdout
        assert [folder for folder in beside if (folder / "ran").exists()] == []

    def test_a_folder_beside_the_installed_package_vanishing_as_the_run_collects_leaves_the_run_alone(
        self, tmp_path: Path,
    ):
        temp = tmp_path / "temp"
        (temp / "another-runs-folder").mkdir(parents=True)
        site = installed_at(temp / "venv" / "Lib" / "site-packages")
        (site / "another_run.py").write_text(ANOTHER_RUN_CLEARING_AWAY_ITS_FOLDER_AS_THIS_ONE_COLLECTS,
                                             encoding="utf-8")

        done = run_pytest_in(a_consumer(tmp_path), "--collect-only", "-p", "another_run",
                             app_support_from=site)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert THE_BLOCKED_WORD_CHECK in done.stdout, done.stdout

    def test_a_whole_run_imports_the_checkouts_package_over_a_copy_installed_beside_this_one(
        self, tmp_path: Path,
    ):
        repo = a_consumer(tmp_path)
        site = installed_at(tmp_path / "venv" / "Lib" / "site-packages")
        for folder, copy in ((repo, "the checkout's"), (site, "the installed")):
            (folder / "example_app").mkdir()
            (folder / "example_app" / "__init__.py").write_text(f'COPY = "{copy}"\n', encoding="utf-8")
        (repo / "tests" / "test_code.py").write_text(A_TEST_OF_WHICH_COPY_OF_THE_REPOS_PACKAGE_IT_IMPORTS,
                                                     encoding="utf-8")

        done = run_pytest_in(repo, "-k", "the_checkouts_own_copy", app_support_from=site)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr

    @pytest.mark.parametrize(("site", "passing_over"), [
        pytest.param("vendor", [], id="a folder the run walks"),
        pytest.param("vendor", ["--ignore=vendor"], id="a folder the run is told to pass over"),
        pytest.param(".venv/Lib/site-packages", [], id="the checkout's own venv"),
    ])
    def test_a_check_installed_inside_the_checkout_is_collected_once_by_a_run_of_the_whole_checkout(
        self, tmp_path: Path, site: str, passing_over: list[str],
    ):
        repo = a_consumer(tmp_path)

        done = run_pytest_in(repo, "--collect-only", ".", *passing_over,
                             app_support_from=installed_at(repo / site))

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert done.stdout.count(THE_BLOCKED_WORD_CHECK) == 1, done.stdout

    def test_this_package_declares_no_pytest_entry_point(self):
        """What makes naming the plugin the *only* way in.

        A `pytest11` entry point would load a plugin in every venv holding this
        package, which is most of them — so a check would arrive in ten repos at
        once, whether or not they asked, and its rollout would be unmeasurable.
        Reproduced while reviewing the content guard: with a fabricated
        dist-info declaring `[pytest11]`, a repo naming no plugin loads it anyway
        and goes red on a planted term.

        Nothing else can catch this. A repo that does not name a plugin is green
        either way today, because without an entry point there is no code path
        to run — so the declaration itself is the thing to watch.
        """
        pyproject = (APP_SUPPORT / "pyproject.toml").read_text(encoding="utf-8")

        assert "pytest11" not in pyproject

    def test_a_shuffled_run_dealt_into_parts_runs_the_blocked_word_check_in_exactly_one_part(
        self, tmp_path: Path,
    ):
        repo = a_consumer(tmp_path)
        (repo / "tests" / "conftest.py").write_text(A_PLUGIN_THAT_SHUFFLES_THE_RUN, encoding="utf-8")
        listed = []
        for part in (1, 2):
            (repo / "conftest.py").write_text(
                A_PLUGIN_THAT_DEALS_THE_RUN_INTO_TWO_PARTS_THE_WAY_PYTEST_TEST_GROUPS_DOES.format(part=part),
                encoding="utf-8")
            done = run_pytest_in(repo, "--collect-only")
            assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
            listed.append(done.stdout)

        assert [THE_BLOCKED_WORD_CHECK in part for part in listed].count(True) == 1, listed
