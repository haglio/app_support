"""What a change takes out of a library, and which open branch of another repo still uses it.

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from app_support.git_files import files_at, git
from app_support.python_source import names_defined, references, spelled_out, top_of

_PYTHON = (".py", ".pyw")
_SPELLED_OUT_IN = (".toml", ".cfg", ".ini", ".yml", ".yaml", ".json", ".vbs", ".cmd", ".bat", ".ps1", ".sh")


def _module_of(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def surface(sources: Mapping[str, str]) -> set[str]:
    found = set()
    for path, source in sources.items():
        module = _module_of(path)
        found.add(module)
        found.update(f"{module}.{name}" for name in names_defined(source))
    return found


def broken_by(reference: str, taken_out: set[str]) -> str | None:
    parts = reference.split(".")
    return next((prefix for end in range(1, len(parts) + 1)
                 if (prefix := ".".join(parts[:end])) in taken_out), None)


def _packages(pyproject: str) -> list[str]:
    find = tomllib.loads(pyproject).get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    if not find.get("include"):
        raise ValueError("pyproject.toml names no package under [tool.setuptools.packages.find] include, "
                         "so there is nothing to read what this change takes out of")
    return find["include"]


def _library_surface(checkout: Path, revision: str) -> set[str]:
    patterns = _packages(files_at(checkout, revision, lambda path: path == "pyproject.toml")["pyproject.toml"])

    def in_a_package(path: str) -> bool:
        top, _, rest = path.partition("/")
        return bool(rest) and path.endswith(".py") and any(fnmatch(top, pattern) for pattern in patterns)

    return surface(files_at(checkout, revision, in_a_package))


def names_taken_out(checkout: Path, base: str, head: str) -> set[str]:
    left_from = git(checkout, "merge-base", base, head).strip()
    return _library_surface(checkout, left_from) - _library_surface(checkout, head)


@dataclass(frozen=True)
class OpenBranch:
    repo: str
    branch: str
    commit: str
    git_dir: Path


@dataclass(frozen=True)
class StillUsed:
    name: str
    branch: OpenBranch
    files: tuple[str, ...]


def _is_read(path: str) -> bool:
    return path.endswith(_PYTHON + _SPELLED_OUT_IN)


def _uses_in(path: str, text: str, packages: Iterable[str]) -> set[str]:
    if path.endswith(_PYTHON):
        try:
            return references(text, packages)
        except SyntaxError:
            pass
    return spelled_out(text, packages)


def still_used(taken_out: set[str] | frozenset[str], branches: Iterable[OpenBranch],
               packages: Iterable[str]) -> list[StillUsed]:
    packages = tuple(packages)
    found = []
    for branch in branches:
        where: dict[str, set[str]] = {}
        for path, text in files_at(branch.git_dir, branch.commit, _is_read).items():
            if any(package in text for package in packages):
                for reference in _uses_in(path, text, packages):
                    if name := broken_by(reference, taken_out):
                        where.setdefault(name, set()).add(path)
        found += [StillUsed(name, branch, tuple(sorted(paths))) for name, paths in sorted(where.items())]
    return found


_OPEN_WORK = """{
  organization(login: "%s") {
    repositories(first: 100, isArchived: false) {
      nodes {
        name
        defaultBranchRef { name }
        pullRequests(states: OPEN, first: 100) { nodes { headRefName isCrossRepository } }
      }
    }
  }
}"""


def _ask_github(query: str) -> str:
    return subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], check=True, capture_output=True,
                          encoding="utf-8").stdout


def open_on_github(org: str, *, but: str, ask: Callable[[str], str] = _ask_github) -> list[tuple[str, str]]:
    repositories = json.loads(ask(_OPEN_WORK % org))["data"]["organization"]["repositories"]["nodes"]
    found = []
    for repository in repositories:
        main = repository["defaultBranchRef"]
        if repository["name"] == but or main is None:
            continue
        found.append((repository["name"], main["name"]))
        found += [(repository["name"], pull["headRefName"])
                  for pull in repository["pullRequests"]["nodes"] if not pull["isCrossRepository"]]
    return found


def fetched(found: Iterable[tuple[str, str]], into: Path, *, url_of: Callable[[str], str]) -> list[OpenBranch]:
    by_repo: dict[str, list[str]] = {}
    for repo, branch in found:
        by_repo.setdefault(repo, []).append(branch)
    branches = []
    for repo, names in by_repo.items():
        git_dir = into / f"{repo}.git"
        git(into, "init", "-q", "--bare", str(git_dir))
        git(git_dir, "fetch", "-q", "--depth=1", "--no-tags", url_of(repo),
            *(f"+refs/heads/{name}:refs/heads/{name}" for name in names))
        branches += [OpenBranch(repo, name, f"refs/heads/{name}", git_dir) for name in names]
    return branches


def main(argv: list[str] | None = None, *, ask: Callable[[str], str] = _ask_github,
         url_of: Callable[[str], str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.taken_out",
        description="Refuse a change to a library that takes out a module or a name another repo's main or "
                    "open pull request still uses.")
    parser.add_argument("--base", required=True, help="the commit the change is made on")
    parser.add_argument("--head", default="HEAD", help="the change (default: HEAD)")
    parser.add_argument("--checkout", type=Path, default=Path.cwd(), help="the library's checkout")
    parser.add_argument("--repo", help="the library's repository, whose own branches are not read "
                                       "(default: the checkout's folder name)")
    parser.add_argument("--org", default="haglio", help="the GitHub organization the repositories are in")
    arguments = parser.parse_args(argv)
    taken = names_taken_out(arguments.checkout, arguments.base, arguments.head)
    if not taken:
        print("This change takes out no module or name.")
        return 0
    found = open_on_github(arguments.org, but=arguments.repo or arguments.checkout.name, ask=ask)
    with tempfile.TemporaryDirectory() as into:
        branches = fetched(found, Path(into), url_of=url_of or (
            lambda repo: f"https://github.com/{arguments.org}/{repo}.git"))
        still = still_used(taken, branches, {top_of(name) for name in taken})
    print(_refusal(still) if still else _clearance(taken, branches))
    return 1 if still else 0


def _refusal(still: list[StillUsed]) -> str:
    return "\n".join([
        ("This change takes out what other work still uses, which would stop that work at its first import once it "
         "takes this release:"),
        *(f"  {each.name}: {each.branch.repo} {each.branch.branch} ({', '.join(each.files)})" for each in still),
        ("Keep each of these until nothing listed here uses it: move that work off it first, then take it out in a "
         "later change.")])


def _clearance(taken: set[str], branches: list[OpenBranch]) -> str:
    repos = _counted(len({branch.repo for branch in branches}), "other repo", "other repos")
    return (f"This change takes out {_listed(sorted(taken))}; read {_counted(len(branches), 'branch', 'branches')} "
            f"of {repos}, and none uses any of it.")


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _counted(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


if __name__ == "__main__":
    raise SystemExit(main())
