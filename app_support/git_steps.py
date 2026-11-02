from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs, run_process_tree

GIT_TIMEOUT_S = 120.0

Run = Callable[..., str]


class StepFailed(Exception):
    pass


def run(arguments: Sequence[str], *, cwd: Path | None = None, timeout: float = GIT_TIMEOUT_S,
        env: Mapping[str, str] | None = None) -> str:
    try:
        finished = run_process_tree(list(arguments), cwd=cwd, text=True, encoding="utf-8", errors="replace",
                                    timeout=timeout, env={**os.environ, **env} if env else None,
                                    stdin=subprocess.DEVNULL, **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        raise StepFailed(f"{_step(arguments)} did not finish in {timeout:g} s") from None
    except OSError as cannot:
        raise StepFailed(f"{_step(arguments)} could not start: {cannot}") from None
    if finished.returncode != 0:
        said = " / ".join(_why_it_failed((finished.stderr or finished.stdout).strip().splitlines()))
        raise StepFailed(f"{_step(arguments)} said: {said or f'exit status {finished.returncode}'}")
    return finished.stdout


def _why_it_failed(printed: list[str]) -> list[str]:
    lines = [line.strip() for line in printed]
    cause = next((line for line in lines if line.startswith(("error:", "fatal:"))), None)
    return [cause, lines[-1]] if cause and cause != lines[-1] else lines[-3:]


def _step(arguments: Sequence[str]) -> str:
    if "pip" in arguments:
        return "pip " + arguments[list(arguments).index("pip") + 1]
    return " ".join(arguments[:2])


def git(checkout: Path, *arguments: str, run: Run) -> str:
    return run(["git", *arguments], cwd=checkout, timeout=GIT_TIMEOUT_S).strip()


def git_or_none(checkout: Path, *arguments: str, run: Run) -> str | None:
    try:
        return git(checkout, *arguments, run=run) or None
    except StepFailed:
        return None


def uncommitted_changes(checkout: Path, *, run: Run) -> str:
    """What ``git status`` says is changed and not committed, asked without the index lock
    a refresh of the index would take from an update running beside it."""
    return run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=checkout, timeout=GIT_TIMEOUT_S,
               env={"GIT_OPTIONAL_LOCKS": "0"}).strip()


def default_branch(checkout: Path, *, run: Run) -> str | None:
    head = git_or_none(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run)
    if head and head.startswith("origin/"):
        return head[len("origin/"):]
    return next((name for name in ("main", "master")
                 if git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", run=run)),
                None)



def is_ancestor(checkout: Path, older: str, newer: str, *, run: Run) -> bool:
    try:
        git(checkout, "merge-base", "--is-ancestor", older, newer, run=run)
    except StepFailed:
        return False
    return True
