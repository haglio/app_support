"""Tests for how a check this package ships reaches a consumer's session, and how a run that loses one ends."""
from __future__ import annotations

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
A_TEST_THAT_LEAVES_A_MARK = """\
from pathlib import Path


def test_the_repos_own():
    Path(__file__).with_name("ran").touch()
"""
A_PLUGIN_THAT_DROPS_THE_BLOCKED_WORD_CHECK = f"""\
def pytest_collection_modifyitems(items):
    items[:] = [item for item in items if item.name != "{THE_BLOCKED_WORD_CHECK}"]
"""
A_PLUGIN_THAT_TAKES_A_CHECK_BACK_OUT_OF_THE_RUNS_ARGUMENTS = """\
import pytest


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    config.args[:] = [arg for arg in config.args if not arg.endswith("{shipped}")]
"""
A_HOOK_THAT_PASSES_OVER_VENDOR = """\
def pytest_ignore_collect(collection_path):
    return collection_path.name == "vendor" or None
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


class TestWhichRunsAreEnforced:
    """The rule itself, without a subprocess in the way.

    The end-to-end cases beside each plugin prove the rule reaches a real
    session; these prove which way each shape of argument is decided, including
    the ones a real session cannot easily be talked into producing.
    """

    class _Config:
        def __init__(self, args):
            self.args = list(args)
            self.stash = pytest.Stash()
            self.pluginmanager = pytest.PytestPluginManager()

    def test_no_arguments_of_its_own_is_a_whole_tree(self):
        """pytest fills these in from `testpaths` or the invocation directory,
        as absolute paths, before any plugin is configured -- so an empty list
        never actually reaches here, and a directory is what does.
        """
        assert shipped_tests.is_a_run_of_whole_trees([str(APP_SUPPORT / "tests")])

    def test_several_directories_are_still_whole_trees(self):
        assert shipped_tests.is_a_run_of_whole_trees(
            [str(APP_SUPPORT / "tests"), str(APP_SUPPORT / "app_support")])

    def test_one_named_file_among_directories_narrows_the_whole_run(self):
        assert not shipped_tests.is_a_run_of_whole_trees(
            [str(APP_SUPPORT / "tests"), str(APP_SUPPORT / "tests" / "test_cli.py")])

    def test_a_node_id_is_not_a_tree(self):
        assert not shipped_tests.is_a_run_of_whole_trees(
            [f"{APP_SUPPORT / 'tests' / 'test_cli.py'}::test_one"])

    def test_nothing_at_all_is_not_a_tree(self):
        """Nothing to enforce against, and adding to it would invent a run."""
        assert not shipped_tests.is_a_run_of_whole_trees([])

    def test_a_check_is_added_once_however_often_it_is_shipped(self):
        """Two copies would collect the same check twice."""
        config = self._Config([str(APP_SUPPORT / "tests")])

        shipped_tests.ship(config, SHIPPED[0], called="a check")
        shipped_tests.ship(config, SHIPPED[0], called="a check")

        assert config.args == [str(SHIPPED[0]), str(APP_SUPPORT / "tests")]

    def test_a_check_shipped_after_another_still_reaches_the_run(self):
        """Every repo in the family names two of these plugins, and the second
        judged the run by the file the first had just put into it: a named file,
        so a narrowed run, and it shipped nothing. That took the blocked-word
        check out of every suite from the day the clock checks joined it.
        """
        config = self._Config([str(APP_SUPPORT / "tests")])

        shipped_tests.ship(config, SHIPPED[0], called="a check")
        shipped_tests.ship(config, SHIPPED[1], called="a check")

        assert sorted(config.args) == sorted([str(APP_SUPPORT / "tests"), *map(str, SHIPPED)])


class TestWhatShippingReachesInAConsumer:
    def test_this_repo_root_offers_a_consumer_only_the_one_name(self):
        """Collecting a shipped file puts this repo's root on the consumer's
        `sys.path` -- measured, under an editable install; under a wheel it is
        site-packages instead -- and a real package anywhere on the path beats a
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

    def test_nothing_this_package_ships_can_smuggle_in_a_conftest(self):
        """pytest loads every conftest.py on the path up from a collected file,
        and a shipped one is collected from inside an installed package.
        Measured: a conftest beside the shipped module, and one at the
        site-packages root above it, both execute inside the consumer's session
        -- so one added here would run arbitrary setup in ten other repos'
        suites, which is not a thing this package may be able to do by accident.
        """
        chains = {d for here in SHIPPED for d in here.parents if APP_SUPPORT in (d, *d.parents)}

        smuggled = sorted(d / "conftest.py" for d in chains if (d / "conftest.py").exists())

        assert SHIPPED, "this package ships no test file to check"
        assert smuggled == [], f"these would load in every consumer's suite: {smuggled}"

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


class TestAShippedCheckIsInTheRunOrTheRunEnds:
    def _consumer(self, tmp_path: Path, *, conftest: str | None = None,
                  options: str = FAMILY_OPTIONS) -> Path:
        repo = tmp_path / "family" / "repo"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(
            f'[tool.pytest.ini_options]\naddopts = "{options}"\ntestpaths = ["tests"]\n',
            encoding="utf-8")
        (repo / "tests" / "test_code.py").write_text(A_TEST_THAT_LEAVES_A_MARK, encoding="utf-8")
        if conftest is not None:
            (repo / "conftest.py").write_text(conftest, encoding="utf-8")
        return repo

    def _installed_in_the_checkout(self, repo: Path, site: str) -> Path:
        shutil.copytree(APP_SUPPORT / "app_support", repo / site / "app_support",
                        ignore=shutil.ignore_patterns("__pycache__"))
        return repo / site

    @pytest.mark.parametrize(("shipped", "called"), [("test_tracked_tree.py", "the blocked-word check"),
                                                     ("test_clocks.py", "the clock checks")])
    def test_a_check_kept_out_of_the_runs_arguments_ends_the_run_before_any_test(
        self, tmp_path: Path, shipped: str, called: str,
    ):
        repo = self._consumer(tmp_path, conftest=A_PLUGIN_THAT_TAKES_A_CHECK_BACK_OUT_OF_THE_RUNS_ARGUMENTS
                              .format(shipped=shipped))

        done = run_pytest_in(repo)

        assert done.returncode == pytest.ExitCode.USAGE_ERROR, done.stdout + done.stderr
        assert f"never collected: {called}" in done.stderr, done.stderr
        assert not (repo / "tests" / "ran").exists()

    def test_a_check_a_plugin_drops_without_deselecting_it_ends_the_run_before_any_test(
        self, tmp_path: Path,
    ):
        repo = self._consumer(tmp_path, conftest=A_PLUGIN_THAT_DROPS_THE_BLOCKED_WORD_CHECK)

        done = run_pytest_in(repo)

        assert done.returncode == pytest.ExitCode.USAGE_ERROR, done.stdout + done.stderr
        assert "the blocked-word check" in done.stderr, done.stderr
        assert not (repo / "tests" / "ran").exists()

    @pytest.mark.parametrize(("site", "args", "conftest"), [
        pytest.param(".venv/Lib/site-packages", [], None, id="the checkout's .venv"),
        pytest.param("vendor", ["--ignore=vendor"], None, id="--ignore"),
        pytest.param("vendor", [], 'collect_ignore = ["vendor"]\n', id="collect_ignore"),
        pytest.param("vendor", [], A_HOOK_THAT_PASSES_OVER_VENDOR, id="pytest_ignore_collect"),
    ])
    def test_a_check_a_run_of_the_whole_checkout_passes_over_ends_the_run(
        self, tmp_path: Path, site: str, args: list[str], conftest: str | None,
    ):
        repo = self._consumer(tmp_path, conftest=conftest)

        done = run_pytest_in(repo, ".", *args,
                             app_support_from=self._installed_in_the_checkout(repo, site))

        assert done.returncode == pytest.ExitCode.USAGE_ERROR, done.stdout + done.stderr
        assert "never collected: the blocked-word check" in done.stderr, done.stderr
        assert not (repo / "tests" / "ran").exists()

    def test_a_check_installed_inside_the_checkout_is_collected_by_a_run_of_the_whole_checkout(
        self, tmp_path: Path,
    ):
        repo = self._consumer(tmp_path)
        site = self._installed_in_the_checkout(repo, "vendor")

        done = run_pytest_in(repo, "--collect-only", ".", app_support_from=site)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert THE_BLOCKED_WORD_CHECK in done.stdout, done.stdout

    @pytest.mark.parametrize("narrowing", [["-k", "not tracked_tree"], ["-m", "not repo_check"]])
    def test_a_check_the_run_was_told_to_deselect_is_left_out_quietly(
        self, tmp_path: Path, narrowing: list[str],
    ):
        done = run_pytest_in(self._consumer(tmp_path), "--collect-only", *narrowing)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert "deselected" in done.stdout, done.stdout
        assert THE_BLOCKED_WORD_CHECK not in done.stdout

    def test_a_check_deselected_by_its_node_id_is_left_out_quietly(self, tmp_path: Path):
        repo = self._consumer(tmp_path)
        listed = run_pytest_in(repo, "--collect-only").stdout.splitlines()
        node_id = next(line for line in listed if line.endswith(f"::{THE_BLOCKED_WORD_CHECK}"))

        done = run_pytest_in(repo, "--collect-only", "--deselect", node_id)

        assert done.returncode == pytest.ExitCode.OK, done.stdout + done.stderr
        assert "1 deselected" in done.stdout, done.stdout

    def test_a_shuffled_run_dealt_into_parts_runs_each_check_in_one_part_and_says_nothing(
        self, tmp_path: Path,
    ):
        repo = self._consumer(tmp_path)
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

    def test_a_run_of_only_its_last_failures_leaves_the_checks_out_and_says_nothing(
        self, tmp_path: Path,
    ):
        repo = self._consumer(tmp_path, options=FAMILY_OPTIONS.replace("-p no:cacheprovider ", ""))
        (repo / "tests" / "test_code.py").write_text("def test_failing():\n    assert False\n",
                                                     encoding="utf-8")
        run_pytest_in(repo)

        done = run_pytest_in(repo, "--lf")

        assert done.returncode == pytest.ExitCode.TESTS_FAILED, done.stdout + done.stderr
        assert "1 failed" in done.stdout, done.stdout
