"""Point this checkout's git hooks at ``tools/githooks``, for it and every worktree of it.

    python -m app_support.githooks [--uninstall]

The setting is written to the repository's shared config, which every worktree
reads, and it is relative, so each worktree runs the hooks its own tree defines.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOOKS_DIR = "tools/githooks"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def main(argv: list[str]) -> int:
    repo = Path(_git("rev-parse", "--show-toplevel").stdout.strip())
    if not (repo / HOOKS_DIR / "pre-commit").exists():
        print(f"no {HOOKS_DIR}/pre-commit in {repo}", file=sys.stderr)
        return 1
    if "--uninstall" in argv:
        _git("config", "--local", "--unset", "core.hooksPath")
        print("core.hooksPath unset; git is back to .git/hooks")
        return 0
    was = _git("config", "--local", "core.hooksPath").stdout.strip() or None
    if was == HOOKS_DIR:
        print(f"already installed: core.hooksPath = {HOOKS_DIR}")
        return 0
    _git("config", "--local", "core.hooksPath", HOOKS_DIR).check_returncode()
    print(f"core.hooksPath was {was!r} — replaced with {HOOKS_DIR!r}" if was else f"core.hooksPath = {HOOKS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
