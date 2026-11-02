from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs, run_process_tree

SCHEMA = 1

METHOD, METHOD_VERSION = "recipe", "recipe_version"

_GIT_TIMEOUT_SECONDS = 10

_OID_HEADER = "# branch.oid "


def _status(directory: Path) -> str | None:
    try:
        done = run_process_tree(["git", "-C", str(directory), "status", "--porcelain=v2", "--branch"],
                                text=True, timeout=_GIT_TIMEOUT_SECONDS, **hidden_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


@cache
def _code_version(directory: str) -> tuple[str | None, bool | None]:
    reported = _status(Path(directory))
    if reported is None:
        return None, None
    lines = reported.splitlines()
    commit = next((line[len(_OID_HEADER):] for line in lines
                   if line.startswith(_OID_HEADER)), None)
    if commit is None or not commit[:1].isalnum():
        return None, None  # git: an unborn HEAD reports "(initial)"
    return commit, any(not line.startswith("#") for line in lines)


def stamp(app: str, *, anchor: str | Path,
          method: str | None = None, method_version: str | None = None,
          recipe: str | None = None, recipe_version: str | None = None) -> dict:
    commit, dirty = _code_version(str(Path(anchor).parent))
    return {"schema": SCHEMA, "app": app, "app_commit": commit, "app_dirty": dirty,
            METHOD: method if method is not None else recipe,
            METHOD_VERSION: method_version if method_version is not None else recipe_version,
            "stamped_at": datetime.now(UTC).isoformat()}
