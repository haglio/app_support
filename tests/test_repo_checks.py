"""Tests for where in a run the checks of the repository itself go.

Every case runs a real pytest against a throwaway repo, and reads the order off
``--collect-only``, which lists a run's tests in the order it will run them.
Every "banned" term here is invented.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from consumer_runs import run_pytest_in

from app_support.sanitize import blocklist_path

TERM = "plantedterm"

PYPROJECT = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.sanitize.pytest_plugin"
testpaths = ["tests"]
"""
THE_FAMILYS_CHECK = "test_no_blocklisted_terms_in_the_tracked_tree"
A_TEST = "def test_what_the_code_does():\n    pass\n"
A_CHECK_OF_ITS_OWN = """\
import pytest

pytestmark = pytest.mark.repo_check


def test_the_whole_tree():
    pass
"""
A_PLUGIN_THAT_REVERSES_EVERY_RUN_LAST = """\
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items):
    yield
    items.reverse()
"""


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "family" / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    return repo


def _run_order(repo: Path) -> list[str]:
    listed = run_pytest_in(repo, "--collect-only").stdout
    return [line.rsplit("::", 1)[-1] for line in listed.splitlines() if "::" in line]


def test_a_blocked_word_ends_a_fail_fast_run_before_any_other_test_runs(tmp_path: Path):
    repo = _repo(tmp_path, {"notes.md": f"this has {TERM} in it\n", "tests/test_code.py": A_TEST})
    blocklist = blocklist_path(repo)
    blocklist.parent.mkdir(parents=True, exist_ok=True)
    blocklist.write_text(f"{TERM}\n", encoding="utf-8")
    for step in (["init", "-b", "main"], ["config", "user.email", "order@example.test"],
                 ["config", "user.name", "Order Test"], ["add", "."],
                 ["commit", "-m", "seed", "--no-verify"]):
        subprocess.run(["git", "-C", str(repo), *step], check=True, capture_output=True)

    done = run_pytest_in(repo, "-x")

    assert "1 failed in" in done.stdout, done.stdout
    assert "notes.md" in done.stdout, done.stdout


def test_the_familys_checks_lead_then_the_repos_own_then_the_rest(tmp_path: Path):
    repo = _repo(tmp_path, {"tests/test_a_code.py": A_TEST, "tests/test_z_tree.py": A_CHECK_OF_ITS_OWN})

    assert _run_order(repo) == [THE_FAMILYS_CHECK, "test_the_whole_tree", "test_what_the_code_does"]


def test_the_checks_still_lead_a_run_another_plugin_reorders_after_everything_else(tmp_path: Path):
    """The merge gate shuffles every run and deals it into parts after collection."""
    repo = _repo(tmp_path, {"tests/conftest.py": A_PLUGIN_THAT_REVERSES_EVERY_RUN_LAST,
                            "tests/test_a_code.py": A_TEST, "tests/test_z_tree.py": A_CHECK_OF_ITS_OWN})

    order = _run_order(repo)

    assert sorted(order[:2]) == sorted([THE_FAMILYS_CHECK, "test_the_whole_tree"]), order
    assert order[2:] == ["test_what_the_code_does"], order
