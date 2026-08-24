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

    def _pytest(self, repo: Path) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(APP_SUPPORT)}
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repo, env=env, capture_output=True, text=True,
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
