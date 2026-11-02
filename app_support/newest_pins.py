"""Every repo of the family takes the newest release of each library it pins, through one
pull request a library's landing opens in it or brings up to date.

Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app_support.dependencies import release_of, repinned, sibling_pins_in
from app_support.wording import listed

BRANCH = "take-the-newest-shared-code"
PYPROJECT = "pyproject.toml"
_RELEASE = re.compile(r"^v\d+(?:\.\d+)*$")
_TAG_REF = re.compile(r"\trefs/tags/(\S+)$", re.MULTILINE)


@dataclass(frozen=True)
class Move:
    library: str
    old: str
    new: str


def newest_taken(pyproject: str, newest: Mapping[str, str]) -> tuple[str, list[Move]]:
    moved, seen = [], set()
    for pin in sibling_pins_in(pyproject):
        tag = newest.get(pin.repo)
        if pin.spec in seen or tag is None or release_of(tag) <= release_of(pin.tag):
            continue
        seen.add(pin.spec)
        pyproject = repinned(pyproject, pin, tag)
        moved.append(Move(pin.repo, pin.tag, tag))
    return pyproject, moved


def newest_release(tags: Sequence[str]) -> str | None:
    return max((tag for tag in tags if _RELEASE.match(tag)), key=release_of, default=None)


class GitHub(Protocol):
    def repos(self) -> list[str]: ...
    def main_of(self, repo: str) -> tuple[str, str] | None: ...
    def file_at(self, repo: str, ref: str, path: str) -> str | None: ...
    def tags(self, repo: str) -> list[str]: ...
    def point(self, repo: str, branch: str, sha: str) -> None: ...
    def commit_pyproject(self, repo: str, parent: str, text: str, *, message: str) -> str: ...
    def open_pull(self, repo: str, branch: str) -> int | None: ...
    def offer(self, repo: str, branch: str, base: str, title: str, body: str) -> int: ...
    def retitle(self, repo: str, number: int, title: str, body: str) -> None: ...
    def arm(self, repo: str, number: int) -> str | None: ...
    def withdraw(self, repo: str, number: int, branch: str, why: str) -> None: ...


@dataclass(frozen=True)
class _Project:
    repo: str
    main: str
    head: str
    text: str


def _projects(github: GitHub) -> list[_Project]:
    found = []
    for repo in github.repos():
        main = github.main_of(repo)
        held = main and github.file_at(repo, main[1], PYPROJECT)
        if held:
            found.append(_Project(repo, *main, held))
    return found


def _releases(moved: list[Move]) -> str:
    return listed([f"{move.library} {move.new}" for move in moved])


def _subject(moved: list[Move]) -> str:
    return "Take " + _releases(moved)


def _body(moved: list[Move]) -> str:
    return ("Moves " + listed([f"{move.library} from {move.old} to {move.new}" for move in moved]) + ".\n\n"
            "Opened by the landing of a library of the family, and brought up to date by each landing after it; "
            "it ships by itself once this repo's checks pass.")


def _bring_up_one(github: GitHub, project: _Project, newest: Mapping[str, str]) -> str | None:
    taken, moved = newest_taken(project.text, newest)
    pull = github.open_pull(project.repo, BRANCH)
    if not moved:
        if pull is None:
            return None
        why = f"{project.main} takes the newest release of each library already"
        github.withdraw(project.repo, pull, BRANCH, why + ".")
        return f"{project.repo}: withdrew #{pull}, as {why}"
    offered = github.file_at(project.repo, BRANCH, PYPROJECT) if pull is not None else None
    if offered == taken:
        return f"{project.repo}: #{pull} already takes {_releases(moved)}"
    github.point(project.repo, BRANCH, github.commit_pyproject(project.repo, project.head, taken,
                                                               message=_subject(moved)))
    if pull is None:
        pull = github.offer(project.repo, BRANCH, project.main, _subject(moved), _body(moved))
    else:
        github.retitle(project.repo, pull, _subject(moved), _body(moved))
    refused = github.arm(project.repo, pull)
    shipping = f" (not set to ship by itself: {refused})" if refused else ""
    return f"{project.repo}: #{pull} {_subject(moved)}{shipping}"


def bring_up(github: GitHub) -> list[str]:
    projects = _projects(github)
    libraries = sorted({pin.repo for project in projects for pin in sibling_pins_in(project.text)})
    newest = {library: tag for library in libraries if (tag := newest_release(github.tags(library)))}
    return [said for project in projects if (said := _bring_up_one(github, project, newest))]


class NotFound(LookupError):
    pass


def _run(command: Sequence[str]) -> str:
    return subprocess.run(list(command), check=True, capture_output=True, encoding="utf-8").stdout


class GhGitHub:
    """The organization on GitHub, asked through the gh command and git."""

    def __init__(self, org: str, *, run: Callable[[Sequence[str]], str] = _run) -> None:
        self.org = org
        self._run = run

    def _api(self, *arguments: str) -> object:
        try:
            said = self._run(["gh", "api", *arguments])
        except subprocess.CalledProcessError as failed:
            if "HTTP 404" in (failed.stderr or ""):
                raise NotFound(arguments[-1]) from None
            raise
        return json.loads(said) if said.strip() else None

    def _found(self, *arguments: str) -> object | None:
        try:
            return self._api(*arguments)
        except NotFound:
            return None

    def repos(self) -> list[str]:
        named = self._run(["gh", "api", "--paginate", f"orgs/{self.org}/repos?per_page=100",
                           "--jq", ".[] | select(.archived | not) | .name"])
        return named.split()

    def main_of(self, repo: str) -> tuple[str, str] | None:
        branch = self._api(f"repos/{self.org}/{repo}")["default_branch"]
        ref = self._found(f"repos/{self.org}/{repo}/git/ref/heads/{branch}")
        return (branch, ref["object"]["sha"]) if ref else None

    def file_at(self, repo: str, ref: str, path: str) -> str | None:
        held = self._found(f"repos/{self.org}/{repo}/contents/{path}?ref={ref}")
        return base64.b64decode(held["content"]).decode("utf-8") if held else None

    def tags(self, repo: str) -> list[str]:
        return _TAG_REF.findall(self._run(["git", "ls-remote", "--tags", "--refs",
                                           f"https://github.com/{self.org}/{repo}.git"]))

    def point(self, repo: str, branch: str, sha: str) -> None:
        if self._found(f"repos/{self.org}/{repo}/git/ref/heads/{branch}") is None:
            try:
                self._api("-X", "POST", f"repos/{self.org}/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}",
                          "-f", f"sha={sha}")
                return
            except subprocess.CalledProcessError:
                pass
        self._api("-X", "PATCH", f"repos/{self.org}/{repo}/git/refs/heads/{branch}", "-f", f"sha={sha}",
                  "-F", "force=true")

    def commit_pyproject(self, repo: str, parent: str, text: str, *, message: str) -> str:
        base = self._api(f"repos/{self.org}/{repo}/git/commits/{parent}")["tree"]["sha"]
        tree = self._api("-X", "POST", f"repos/{self.org}/{repo}/git/trees", "-f", f"base_tree={base}",
                         "-f", f"tree[][path]={PYPROJECT}", "-f", "tree[][mode]=100644", "-f", "tree[][type]=blob",
                         "-f", f"tree[][content]={text}")["sha"]
        return self._api("-X", "POST", f"repos/{self.org}/{repo}/git/commits", "-f", f"message={message}",
                         "-f", f"tree={tree}", "-f", f"parents[]={parent}")["sha"]

    def open_pull(self, repo: str, branch: str) -> int | None:
        pulls = self._api(f"repos/{self.org}/{repo}/pulls?head={self.org}:{branch}&state=open")
        return pulls[0]["number"] if pulls else None

    def offer(self, repo: str, branch: str, base: str, title: str, body: str) -> int:
        try:
            return self._api("-X", "POST", f"repos/{self.org}/{repo}/pulls", "-f", f"title={title}",
                             "-f", f"head={branch}", "-f", f"base={base}", "-f", f"body={body}")["number"]
        except subprocess.CalledProcessError:
            opened = self.open_pull(repo, branch)
            if opened is None:
                raise
            return opened

    def retitle(self, repo: str, number: int, title: str, body: str) -> None:
        self._api("-X", "PATCH", f"repos/{self.org}/{repo}/pulls/{number}", "-f", f"title={title}",
                  "-f", f"body={body}")

    def arm(self, repo: str, number: int) -> str | None:
        try:
            self._run(["gh", "pr", "merge", str(number), "--repo", f"{self.org}/{repo}", "--auto"])
        except subprocess.CalledProcessError as refused:
            return (refused.stderr or str(refused)).strip()
        return None

    def withdraw(self, repo: str, number: int, branch: str, why: str) -> None:
        self._api("-X", "POST", f"repos/{self.org}/{repo}/issues/{number}/comments", "-f", f"body={why}")
        self._api("-X", "PATCH", f"repos/{self.org}/{repo}/pulls/{number}", "-f", "state=closed")
        self._api("-X", "DELETE", f"repos/{self.org}/{repo}/git/refs/heads/{branch}")


def main(argv: list[str] | None = None, *, github: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.newest_pins",
        description="In every repo of the organization that pins a library of the family at a tag, open or bring "
                    "up to date one pull request taking the newest release of each.")
    parser.add_argument("--org", default="haglio")
    arguments = parser.parse_args(argv)
    for said in bring_up(github or GhGitHub(arguments.org)):
        print(said)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
