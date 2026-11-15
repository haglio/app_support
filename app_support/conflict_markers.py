from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from app_support.git_files import git

FIXTURE_ATTRIBUTE = "conflict-marker-fixture"
STAGED = "staged"
_A_MARKER = re.compile(r"^(<{7}|>{7})( |$)")
_COMMIT = "commit "
_DIFF = ("--no-color", "--no-ext-diff", "-U0")


@dataclass(frozen=True)
class Leftover:
    commit: str
    path: str
    line: str


def assert_no_commit_holds_a_leftover(repo: Path, *, since: str = "origin/main") -> None:
    if not _in_a_repository(repo):
        return
    assert _resolves(repo, since), (
        f"{repo} has no {since} to judge this branch's commits against, so none of them was read")
    found = in_commits(repo, since=since)
    assert not found, told_of(repo, found)


def in_commits(repo: Path, *, since: str = "origin/main") -> list[Leftover]:
    return _not_fixtures(repo, list(_added_markers(_git_quoting_nothing(
        repo, "log", "--reverse", *_DIFF, "--diff-merges=first-parent", "-p", f"--format={_COMMIT}%H",
        f"{since}..HEAD"))))


def in_staged(repo: Path) -> list[Leftover]:
    return _not_fixtures(repo, list(_added_markers(_git_quoting_nothing(repo, "diff", "--cached", *_DIFF),
                                                   commit=STAGED)))


def refuse_a_staged_leftover(hook_argv: Sequence[str]) -> int:
    found = in_staged(Path.cwd()) if "--staged" in hook_argv else []
    if found:
        print(told_of(Path.cwd(), found), file=sys.stderr)
    return 1 if found else 0


def told_of(repo: Path, found: Sequence[Leftover]) -> str:
    return ("lines a merge conflict's markers begin, which git writes into a file it could not merge;"
            " finish that merge in the commit that made it:\n"
            + "\n".join(f"  {_named(repo, leftover.commit)}: {leftover.path}: {leftover.line}" for leftover in found)
            + f"\na file that has to carry such lines as a test's fixture is given {FIXTURE_ATTRIBUTE} in .gitattributes")


def _named(repo: Path, commit: str) -> str:
    if commit == STAGED:
        return "the commit being made"
    return f"{commit[:12]} {git(repo, 'show', '-s', '--format=%s', commit).strip()}"


def _git_quoting_nothing(repo: Path, *args: str) -> str:
    return git(repo, "-c", "core.quotePath=false", *args)


def _added_markers(told: str, *, commit: str = "") -> Iterator[Leftover]:
    path, in_header = "", False
    for line in told.splitlines():
        if line.startswith(_COMMIT):
            commit, in_header = line.removeprefix(_COMMIT), False
        elif line.startswith("diff --git "):
            in_header = True
        elif in_header and line.startswith("+++ "):
            path = line.removeprefix("+++ ").removeprefix("b/")
        elif line.startswith("@@"):
            in_header = False
        elif not in_header and line.startswith("+") and _A_MARKER.match(line[1:]):
            yield Leftover(commit, path, line[1:])


def _not_fixtures(repo: Path, found: list[Leftover]) -> list[Leftover]:
    fixtures = _fixtures_among(repo, {leftover.path for leftover in found})
    return [leftover for leftover in found if leftover.path not in fixtures]


def _fixtures_among(repo: Path, paths: set[str]) -> set[str]:
    if not paths:
        return set()
    told = subprocess.run(["git", "-C", str(repo), "check-attr", "-z", "--stdin", FIXTURE_ATTRIBUTE],
                          input="\0".join(sorted(paths)) + "\0", capture_output=True, encoding="utf-8",
                          check=True).stdout.split("\0")
    return {path for path, _name, value in zip(told[0::3], told[1::3], told[2::3], strict=False) if value == "set"}


def _in_a_repository(repo: Path) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, check=False).returncode == 0


def _resolves(repo: Path, revision: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
                          capture_output=True, check=False).returncode == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app_support.conflict_markers")
    parser.add_argument("--since", default="origin/main", help="Judge every commit after this one.")
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        assert_no_commit_holds_a_leftover(Path.cwd(), since=args.since)
    except AssertionError as refused:
        print(refused, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
