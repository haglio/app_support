"""Tests for the guard's pytest plugin — the enforcement a repo gets by asking.

The check itself is one line in a consumer's pyproject; what these prove is that
the line does something. Every case runs a real pytest against a real throwaway
git repo, because the only failure that matters here is a suite that stays green
while a blocklisted term sits in a tracked file — and a plugin that quietly
contributed nothing would look exactly like a repo that is clean.

Every "banned" term here is invented, like every other fixture value in this
suite.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app_support.sanitize import blocklist_path, pytest_plugin

APP_SUPPORT = Path(__file__).resolve().parents[1]
TERM = "plantedterm"

PYPROJECT = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.sanitize.pytest_plugin"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _arm(repo: Path, terms: str) -> Path:
    """Put a list where the guard will look for it, by asking the guard.

    These cases are about what the plugin does once terms resolve, not about
    where they were found; ``test_sanitize_guard.TestBlocklistPath`` pins the
    layout against literal paths, and this reads it from there.
    """
    path = blocklist_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(terms, encoding="utf-8")
    return path


class TestWhichRunsAreEnforced:
    """The rule itself, without a subprocess in the way.

    The end-to-end cases below prove the rule reaches a real session; these
    prove which way each shape of argument is decided, including the ones a real
    session cannot easily be talked into producing.
    """

    class _Config:
        def __init__(self, args):
            self.args = list(args)

    def test_no_arguments_of_its_own_is_a_whole_tree(self):
        """pytest fills these in from `testpaths` or the invocation directory,
        as absolute paths, before any plugin is configured -- so an empty list
        never actually reaches here, and a directory is what does.
        """
        assert pytest_plugin.is_a_run_of_whole_trees([str(APP_SUPPORT / "tests")])

    def test_several_directories_are_still_whole_trees(self):
        assert pytest_plugin.is_a_run_of_whole_trees(
            [str(APP_SUPPORT / "tests"), str(APP_SUPPORT / "app_support")])

    def test_one_named_file_among_directories_narrows_the_whole_run(self):
        assert not pytest_plugin.is_a_run_of_whole_trees(
            [str(APP_SUPPORT / "tests"), str(APP_SUPPORT / "tests" / "test_cli.py")])

    def test_a_node_id_is_not_a_tree(self):
        assert not pytest_plugin.is_a_run_of_whole_trees(
            [f"{APP_SUPPORT / 'tests' / 'test_cli.py'}::test_one"])

    def test_nothing_at_all_is_not_a_tree(self):
        """Nothing to enforce against, and appending to it would invent a run."""
        assert not pytest_plugin.is_a_run_of_whole_trees([])

    def test_the_check_is_added_once_however_often_this_is_configured(self):
        """Two copies would collect the same check twice."""
        config = self._Config([str(APP_SUPPORT / "tests")])

        pytest_plugin.pytest_configure(config)
        pytest_plugin.pytest_configure(config)

        assert len(config.args) == 2, config.args


class TestTheGuardPlugin:
    def _repo(self, tmp_path: Path, *, blocklist: str | None, tracked: str) -> Path:
        repo = tmp_path / "family" / "repo"
        repo.mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        if blocklist is not None:
            _arm(repo, blocklist)
        (repo / "notes.md").write_text(tracked, encoding="utf-8")
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "guard@example.test")
        _git(repo, "config", "user.name", "Guard Test")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "seed", "--no-verify")
        return repo

    def _pytest(
        self, repo: Path, *args: str, cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(APP_SUPPORT)}
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *args],
            cwd=cwd or repo, env=env, capture_output=True, text=True,
        )

    def test_a_planted_term_in_a_tracked_file_fails_the_run(self, tmp_path: Path):
        """The negative control the whole plugin is for. If this ever passes,
        every repo that adopted the line is running a check of nothing.
        """
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")

        done = self._pytest(repo)

        assert done.returncode != 0, done.stdout
        assert "notes.md" in done.stdout

    def test_a_clean_tracked_tree_passes(self, tmp_path: Path):
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")

        assert self._pytest(repo).returncode == 0

    def test_a_checkout_with_no_blocklist_says_so_instead_of_passing(self, tmp_path: Path):
        """A public clone and a fresh CI checkout both arrive without the
        git-ignored overlay. Neither can be taken down over it -- the exit code
        stays 0 -- but neither may report a pass either: that is what made this
        check a silent no-op on every merge queue in the family, reading exactly
        like a tree that had been scanned.
        """
        repo = self._repo(tmp_path, blocklist=None, tracked=f"this has {TERM} in it\n")

        done = self._pytest(repo)

        assert done.returncode == 0
        assert "1 passed" not in done.stdout
        assert "1 skipped" in done.stdout
        assert "NOT scanned" in done.stdout

    def test_a_source_tree_with_no_git_at_all_says_so_too(self, tmp_path: Path):
        """There is nothing to enforce against without a checkout to ask. A
        source archive and a stripped CI checkout both arrive this way, and a
        plugin that took either of them down would be removed from every repo by
        lunchtime -- so it says what it could not do and lets the run finish.
        """
        repo = tmp_path / "unpacked"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        done = self._pytest(repo)

        assert done.returncode == 0, done.stdout
        assert "1 passed, 1 skipped" in done.stdout
        assert "NOT scanned" in done.stdout

    def test_the_reason_reaches_a_log_that_was_not_asked_for_skip_reasons(self, tmp_path: Path):
        """`pytest -q` prints skip reasons only under `-rs`, and the family's
        gates all run a bare `-q`. The warnings summary needs no flag, so the
        reason travels with the skip.
        """
        repo = self._repo(tmp_path, blocklist=None, tracked="perfectly clean\n")

        done = self._pytest(repo)

        assert "warnings summary" in done.stdout
        assert "SANITIZE GUARD UNARMED" in done.stdout

    def test_an_untracked_file_is_not_the_repos_problem(self, tmp_path: Path):
        """Only what is published can leak. A scratch file beside the checkout
        is not going anywhere, and failing on it would make the check
        unusable.
        """
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")
        (repo / "scratch.md").write_text(f"this has {TERM} in it\n", encoding="utf-8")

        assert self._pytest(repo).returncode == 0

    def test_an_armed_checkout_with_nothing_tracked_is_refused_not_reported_clean(
        self, tmp_path: Path,
    ):
        """A pass that scanned no files says the same word as a pass that
        scanned the tree, and the second is the only one worth anything. The
        blocklist half of that hole is handled where the terms are resolved;
        this is the other half -- terms in hand, and a walk that came back with
        nothing to read.
        """
        repo = tmp_path / "family" / "empty"
        repo.mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        _arm(repo, f"{TERM}\n")
        (repo / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")
        _git(repo, "init", "-b", "main")

        done = self._pytest(repo)

        assert done.returncode != 0, done.stdout
        assert "no files at all" in done.stdout

    def test_a_directory_run_is_still_a_run_of_the_whole_tree(self, tmp_path: Path):
        """`pytest tests/` is the command this family's own instructions give,
        and it has narrowed nothing -- so it enforces, exactly as a bare run
        does.
        """
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        assert self._pytest(repo, "tests").returncode != 0

    def test_a_run_started_from_a_subdirectory_still_enforces(self, tmp_path: Path):
        """`testpaths` is relative to the root directory, not to wherever pytest
        was typed. Judging it against the working directory alone made this look
        like a narrowed run and skipped the guard -- silently, which is the one
        failure this check exists not to have.
        """
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "pyproject.toml").write_text(
            PYPROJECT + 'testpaths = ["tests"]\n', encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_local.py").write_text(
            "def test_local():\n    assert True\n", encoding="utf-8")

        done = self._pytest(repo, cwd=repo / "tests")

        assert done.returncode != 0, done.stdout

    def test_a_run_that_names_one_file_leaves_the_tree_alone(self, tmp_path: Path):
        """Narrowed on purpose. Enforcing here would put a whole-tree scan in
        front of a one-test run, and would land the guard in the middle of any
        test that shells out to pytest against a chosen file and counts what
        came back -- which four repos in this family do.
        """
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        target = repo / "tests" / "test_local.py"
        target.write_text("def test_local():\n    assert True\n", encoding="utf-8")

        done = self._pytest(repo, str(target))

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout

    def test_a_run_that_names_one_test_leaves_the_tree_alone(self, tmp_path: Path):
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "tests").mkdir()
        target = repo / "tests" / "test_local.py"
        target.write_text("def test_local():\n    assert True\n", encoding="utf-8")

        done = self._pytest(repo, f"{target}::test_local")

        assert done.returncode == 0, done.stdout
        assert "1 passed" in done.stdout

    def test_the_guard_itself_never_reaches_for_pytest(self):
        """The git hooks run `python -m app_support.sanitize` on whatever
        interpreter they find, which is routinely a bare one with no pytest in
        it. An import of pytest anywhere under `app_support.sanitize` would stop
        every commit in every repo that installed these hooks, and the plugin
        module sitting in the same package is exactly how that gets in.
        """
        probe = (
            "import sys, app_support.sanitize\n"
            "print(sorted(m for m in sys.modules if m.startswith('pytest')"
            " or m.startswith('_pytest')))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=APP_SUPPORT, env={**os.environ, "PYTHONPATH": str(APP_SUPPORT)},
            capture_output=True, text=True,
        )

        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == "[]", done.stdout

    def test_this_repo_root_offers_a_consumer_only_the_one_name(self):
        """Collecting the shipped file puts this repo's root at the front of the
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
        and this one is collected from inside an installed package. Measured: a
        conftest beside the shipped module, and one at the site-packages root
        above it, both execute inside the consumer's session -- so one added
        here would run arbitrary setup in ten other repos' suites, which is not
        a thing this package may be able to do by accident.
        """
        here = APP_SUPPORT / "app_support" / "sanitize" / "test_tracked_tree.py"
        chain = [d for d in here.parents if APP_SUPPORT in (d, *d.parents)]

        smuggled = [d / "conftest.py" for d in chain if (d / "conftest.py").exists()]

        assert smuggled == [], f"these would load in every consumer's suite: {smuggled}"

    def test_this_package_declares_no_pytest_entry_point(self):
        """What makes the line above the *only* way in.

        A `pytest11` entry point would load this plugin in every venv holding
        this package, which is most of them — so the check would arrive in ten
        repos at once, whether or not they asked, and stage two's rollout would
        be unmeasurable. Reproduced while reviewing this branch: with a
        fabricated dist-info declaring `[pytest11]`, a repo naming no plugin
        loads it anyway and goes red on a planted term.

        Nothing else can catch this. A repo that does not name the plugin is
        green either way today, because without an entry point there is no code
        path to run — so the declaration itself is the thing to watch.
        """
        pyproject = (APP_SUPPORT / "pyproject.toml").read_text(encoding="utf-8")

        assert "pytest11" not in pyproject

    def test_without_the_plugin_line_nothing_is_contributed(self, tmp_path: Path):
        """The other half of the control: the check arrives *because* a repo
        asked for it. If it turned up anyway, adopting it in stage two would be
        a no-op and every measurement of the rollout would be a fiction.
        """
        repo = self._repo(
            tmp_path, blocklist=f"{TERM}\n", tracked=f"this has {TERM} in it\n")
        (repo / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider"\n',
            encoding="utf-8")

        done = self._pytest(repo)

        # Nothing to run at all, which pytest reports as exit code 5.
        assert done.returncode == 5, done.stdout
