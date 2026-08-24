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

APP_SUPPORT = Path(__file__).resolve().parents[1]
TERM = "plantedterm"

PYPROJECT = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.sanitize.pytest_plugin"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TestTheGuardPlugin:
    def _repo(self, tmp_path: Path, *, blocklist: str | None, tracked: str) -> Path:
        repo = tmp_path / "repo"
        (repo / "sanitize").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        # Ignored exactly as in the real repos: the blocklist is a catalogue of
        # every term, so a tracked copy would fail the check it exists to power.
        (repo / ".gitignore").write_text(
            "sanitize/blocklist.local.txt\n", encoding="utf-8")
        if blocklist is not None:
            (repo / "sanitize" / "blocklist.local.txt").write_text(
                blocklist, encoding="utf-8")
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

    def test_a_checkout_with_no_blocklist_has_nothing_to_enforce(self, tmp_path: Path):
        """A public clone and a fresh CI checkout both arrive without the
        git-ignored overlay, and must run green rather than red -- deliberately
        a no-op and not a skip, so the run stays clean either way.
        """
        repo = self._repo(tmp_path, blocklist=None, tracked=f"this has {TERM} in it\n")

        done = self._pytest(repo)

        assert done.returncode == 0
        assert "1 passed" in done.stdout

    def test_an_untracked_file_is_not_the_repos_problem(self, tmp_path: Path):
        """Only what is published can leak. A scratch file beside the checkout
        is not going anywhere, and failing on it would make the check
        unusable.
        """
        repo = self._repo(tmp_path, blocklist=f"{TERM}\n", tracked="perfectly clean\n")
        (repo / "scratch.md").write_text(f"this has {TERM} in it\n", encoding="utf-8")

        assert self._pytest(repo).returncode == 0

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
            "import sys, app_support.sanitize, app_support.sanitize.harvest\n"
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
