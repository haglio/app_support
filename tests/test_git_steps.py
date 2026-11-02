from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app_support import git_steps
from app_support.git_steps import StepFailed


def _git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git("init", "-q", "-b", "trunk", cwd=tmp_path)
    return tmp_path


def _commit(repository: Path, message: str) -> str:
    _git("-c", "user.email=someone@example.com", "-c", "user.name=Someone", "commit", "-q", "--allow-empty",
         "-m", message, cwd=repository)
    return _git("rev-parse", "HEAD", cwd=repository).strip()


def test_a_step_that_does_not_finish_in_time_says_so():
    with pytest.raises(StepFailed, match=r"did not finish in 0.2 s"):
        git_steps.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.2)


def test_a_step_that_cannot_start_says_so(tmp_path: Path):
    with pytest.raises(StepFailed, match="could not start"):
        git_steps.run([str(tmp_path / "no such program.exe")])


def test_a_failed_step_quotes_what_git_gave_as_the_cause():
    printing = "import sys; print('warning: first\\nfatal: the cause\\nlast', file=sys.stderr); sys.exit(1)"

    with pytest.raises(StepFailed, match="fatal: the cause / last"):
        git_steps.run([sys.executable, "-c", printing])


def test_a_failed_step_with_nothing_to_say_names_its_exit_status():
    with pytest.raises(StepFailed, match="exit status 3"):
        git_steps.run([sys.executable, "-c", "import sys; sys.exit(3)"])


def test_a_pip_step_is_named_for_what_pip_was_asked():
    with pytest.raises(StepFailed, match=r"^pip install said"):
        git_steps.run([sys.executable, "-c", "import sys; sys.exit(1)", "pip", "install"])


def test_git_or_none_answers_none_where_git_refuses(repository: Path):
    assert git_steps.git_or_none(repository, "rev-parse", "--verify", "no-such-ref", run=git_steps.run) is None


def test_the_default_branch_falls_back_to_a_local_main(repository: Path):
    _git("-c", "user.email=someone@example.com", "-c", "user.name=Someone", "checkout", "-q", "-b", "main",
         cwd=repository)
    _commit(repository, "first")

    assert git_steps.default_branch(repository, run=git_steps.run) == "main"


def test_a_folder_with_no_branch_to_follow_has_no_default_branch(repository: Path):
    assert git_steps.default_branch(repository, run=git_steps.run) is None


def test_an_older_commit_is_an_ancestor_of_a_newer_one_and_not_the_reverse(repository: Path):
    older, newer = _commit(repository, "first"), _commit(repository, "second")

    assert git_steps.is_ancestor(repository, older, newer, run=git_steps.run)
    assert not git_steps.is_ancestor(repository, newer, older, run=git_steps.run)


def test_uncommitted_changes_names_a_changed_tracked_file(repository: Path):
    (repository / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=repository)
    _commit(repository, "first")
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")

    assert "tracked.txt" in git_steps.uncommitted_changes(repository, run=git_steps.run)
