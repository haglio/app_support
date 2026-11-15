from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from app_support.git_files import git

_URGENT = re.compile(r"^Urgent:\s*\S", re.MULTILINE)


def _what_an_app_installs(pyproject: str) -> dict:
    held = tomllib.loads(pyproject)
    held.get("project", {}).get("optional-dependencies", {}).pop("dev", None)
    return held


def _packages(installed: dict) -> list[str]:
    return installed.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("include", [])


def makes_a_release(changed: Iterable[str], old_pyproject: str, new_pyproject: str) -> bool:
    installed = _what_an_app_installs(new_pyproject)
    return (installed != _what_an_app_installs(old_pyproject)
            or any(fnmatch(path.split("/")[0], package) for path in changed for package in _packages(installed)))


def is_urgent(messages: Iterable[str]) -> bool:
    return any(_URGENT.search(message) for message in messages)


def _last_release(checkout: Path) -> str | None:
    try:
        return git(checkout, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD").strip()
    except subprocess.CalledProcessError:
        return None


def _pyproject_at(checkout: Path, ref: str) -> str:
    return git(checkout, "show", f"{ref}:pyproject.toml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.releases",
        description="Say whether the landing at HEAD makes a release, changing code an app installs since the "
                    "last one, and whether a commit since then asks with an Urgent: trailer to reach the apps at "
                    "once, as lines a GitHub workflow appends to $GITHUB_OUTPUT.")
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    checkout = parser.parse_args(argv).checkout
    last = _last_release(checkout)
    since = f"{last}..HEAD" if last else "HEAD"
    messages = git(checkout, "log", "--format=%B%x00", since).split("\0")
    release = last is None or makes_a_release(git(checkout, "diff", "--name-only", last, "HEAD").split(),
                                              _pyproject_at(checkout, last), _pyproject_at(checkout, "HEAD"))
    print(f"release={str(release).lower()}\nurgent={str(is_urgent(messages)).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
