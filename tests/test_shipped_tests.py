"""Tests for how a check this package ships reaches a consumer's session."""
from __future__ import annotations

from pathlib import Path

from app_support import shipped_tests

APP_SUPPORT = Path(__file__).resolve().parents[1]
SHIPPED = sorted((APP_SUPPORT / "app_support").rglob("test_*.py"))


class TestWhichRunsAreEnforced:
    """The rule itself, without a subprocess in the way.

    The end-to-end cases beside each plugin prove the rule reaches a real
    session; these prove which way each shape of argument is decided, including
    the ones a real session cannot easily be talked into producing.
    """

    class _Config:
        def __init__(self, args):
            self.args = list(args)

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
        """Nothing to enforce against, and appending to it would invent a run."""
        assert not shipped_tests.is_a_run_of_whole_trees([])

    def test_a_check_is_added_once_however_often_it_is_shipped(self):
        """Two copies would collect the same check twice."""
        config = self._Config([str(APP_SUPPORT / "tests")])

        shipped_tests.ship(config, SHIPPED[0])
        shipped_tests.ship(config, SHIPPED[0])

        assert config.args == [str(APP_SUPPORT / "tests"), str(SHIPPED[0])]


class TestWhatShippingReachesInAConsumer:
    def test_this_repo_root_offers_a_consumer_only_the_one_name(self):
        """Collecting a shipped file puts this repo's root at the front of the
        consumer's `sys.path` -- measured, under an editable install; under a
        wheel it is site-packages instead. Whatever top-level names that
        directory publishes are then offered to ten other suites ahead of their
        own, and `tools` and `tests` are names every one of them uses.

        It publishes only `app_support` today because nothing else beside it
        carries an `__init__.py`, so the rest are namespace portions and lose to
        a real package of the same name. That is load-bearing and invisible, so
        it is pinned here: the day this repo grows a `tests/__init__.py` is the
        day ten suites import the wrong `tests`.
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
