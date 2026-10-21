"""``python -m app_support.hotfix``, run from an agent's worktree: its branch's fix into the app's production checkout now.

The fix goes onto the commit production runs or is about to, passes the checks the repo
names in ``[tool.haglio.hotfix]`` and the tests the branch changed, and is handed to the
production updater, which keeps it until the same fix ships the usual way.

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from app_support import production_update
from app_support.dependencies import SiblingPin, sibling_pins_in
from app_support.logging_utils import configure_logging
from app_support.production_update import (
    HOTFIX_REF,
    InUse,
    Outcome,
    Run,
    StepFailed,
    hotfix_message,
)
from app_support.subprocess_utils import hidden_subprocess_kwargs

CHECKS_TIMEOUT_S = 10 * 60.0
NOTHING_ASKED_FOR = "0" * 40
Check = Callable[[Path, list[str], Path], None]
BringUp = Callable[[Path], Outcome]


class Refused(Exception):
    pass


def _git(place: Path, *arguments: str, run: Run) -> str:
    return run(["git", *arguments], cwd=place).strip()


def hotfix(worktree: Path, *, run: Run = production_update.run, check: Check, bring_up: BringUp) -> str:
    worktree, production, shipped = _a_fix_ready_to_go(Path(worktree), run=run)
    fix = f"{shipped}..{_git(worktree, 'rev-parse', 'HEAD', run=run)}"
    base = production_update.heading_for(production, run=run)
    asked_before = _asked_for(production, run=run)
    with _a_checkout_of(production, base, run=run) as place:
        patch = place.parent / "fix.patch"
        _git(worktree, "diff", "--binary", f"--output={patch}", f"{shipped}...HEAD", run=run)
        try:
            _git(place, "apply", "--3way", "--index", str(patch), run=run)
        except StepFailed as failed:
            clashing = ", ".join(_git(place, "diff", "--name-only", "--diff-filter=U", run=run).split())
            raise Refused(f"the fix needs changes production does not run yet ({clashing or failed}); "
                          f"ship it the usual way") from None
        _git(place, "commit", "-q", "--no-verify", "-m", _message(worktree, fix, run=run), run=run)
        made = _git(place, "rev-parse", "HEAD", run=run)
        changed = _git(worktree, "diff", "--name-only", f"{shipped}...HEAD", run=run).splitlines()
        check(production / ".venv" / "Scripts" / "python.exe", _checks(place, changed), place)
        try:
            _git(place, "update-ref", HOTFIX_REF, made, asked_before, run=run)
        except StepFailed:
            raise Refused("another hotfix was asked for while this one was being made; run the route again, "
                          "and it builds on that one") from None
    return _what_production_did(production, made, bring_up(production), run=run)


def _a_fix_ready_to_go(worktree: Path, *, run: Run) -> tuple[Path, Path, str]:
    worktree = Path(_git(worktree, "rev-parse", "--show-toplevel", run=run))
    if _git(worktree, "status", "--porcelain", "--untracked-files=no", run=run):
        raise Refused("this worktree has uncommitted changes; commit the fix first")
    production = Path(_git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir", run=run)).parent
    shipped = f"refs/remotes/origin/{production_update.default_branch(production, run=run)}"
    if not _git(worktree, "rev-list", f"{shipped}..HEAD", run=run):
        raise Refused(f"this branch has nothing {shipped.removeprefix('refs/remotes/')} lacks")
    if _pins_at(worktree, shipped, run=run) != _pins_at(worktree, "HEAD", run=run):
        raise Refused("the fix moves a pin of the shared code, which production does not have yet; "
                      "ship it the usual way")
    return worktree, production, shipped


def _what_production_did(production: Path, made: str, outcome: Outcome, *, run: Run) -> str:
    if _git(production, "rev-parse", "HEAD", run=run) == made:
        return f"production {production.name} runs the hotfix {made[:8]} now"
    if production_update.waits_for_programs_to_close(production):
        return f"production {production.name} takes the hotfix {made[:8]} once its app closes ({outcome.said})"
    raise Refused(f"production {production.name} has the hotfix {made[:8]} asked for but did not take it: "
                  f"{outcome.said}")


def _asked_for(production: Path, *, run: Run) -> str:
    try:
        return _git(production, "rev-parse", "--verify", "--quiet", HOTFIX_REF, run=run)
    except StepFailed:
        return NOTHING_ASKED_FOR


def run_checks(python: Path, tests: list[str], place: Path) -> None:
    command = [str(python), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests]
    try:
        finished = subprocess.run(command, cwd=place, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=CHECKS_TIMEOUT_S, stdin=subprocess.DEVNULL,
                                  **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        raise Refused(f"the checks did not finish in {CHECKS_TIMEOUT_S / 60:g} minutes") from None
    if finished.returncode != 0:
        said = (finished.stdout + finished.stderr).strip().splitlines()[-12:]
        raise Refused("a check failed:\n" + "\n".join(said))


def _pins_at(worktree: Path, commit: str, *, run: Run) -> list[SiblingPin]:
    try:
        return sibling_pins_in(_git(worktree, "show", f"{commit}:pyproject.toml", run=run))
    except StepFailed:
        return []


def _message(worktree: Path, fix: str, *, run: Run) -> str:
    commits = [line.split("\x1f") for line in _git(worktree, "log", "--reverse", "--format=%ae\x1f%at\x1f%s", fix,
                                                    run=run).splitlines()]
    return hotfix_message(commits[0][2], [(email, int(seconds)) for email, seconds, _ in commits])


def _checks(place: Path, changed: list[str]) -> list[str]:
    tool = tomllib.loads((place / "pyproject.toml").read_text(encoding="utf-8")).get("tool", {})
    named = list(tool.get("haglio", {}).get("hotfix", {}).get("checks", []))
    if not named:
        raise Refused("this repo names no checks in [tool.haglio.hotfix], so its fixes ship the usual way")
    collected = tool.get("pytest", {}).get("ini_options", {})
    tests = [path for path in changed if (place / path).is_file() and path not in named
             and _a_test_the_suite_runs(PurePosixPath(path), collected.get("testpaths"),
                                        collected.get("norecursedirs", []))]
    return named + tests


def _a_test_the_suite_runs(path: PurePosixPath, roots: list[str] | None, passed_over: list[str]) -> bool:
    return (path.name.startswith("test_") and path.suffix == ".py"
            and (roots is None or any(path.is_relative_to(root) for root in roots))
            and not any(fnmatch.fnmatch(folder, pattern) for folder in path.parent.parts for pattern in passed_over))


@contextlib.contextmanager
def _a_checkout_of(production: Path, commit: str, *, run: Run):
    room = Path(tempfile.mkdtemp(prefix="hotfix-"))
    place = room / "hotfix"
    _git(production, "worktree", "add", "--detach", str(place), commit, run=run)
    try:
        yield place
    finally:
        _git(production, "worktree", "remove", "--force", str(place), run=run)
        shutil.rmtree(room, ignore_errors=True)


def bring_up_now(checkout: Path, *, state: Path, in_use: InUse = production_update.running_from) -> Outcome:
    return production_update.before_launch(checkout, checkout.parent, state, in_use=in_use)[checkout.name]


def main(argv: Sequence[str] | None = None, *, state: Path | None = None) -> int:
    argparse.ArgumentParser(prog="python -m app_support.hotfix", description=__doc__.splitlines()[0]).parse_args(argv)
    state = state or Path(production_update.__file__).resolve().parents[1] / "state"
    try:
        print(hotfix(Path.cwd(), check=run_checks, bring_up=lambda checkout: _logged_bring_up(checkout, state)))
    except (Refused, StepFailed) as refused:
        print(f"refused: {refused}")
        return 1
    return 0


def _logged_bring_up(checkout: Path, state: Path) -> Outcome:
    configure_logging("production_update", state / production_update.LOG_NAME)
    return bring_up_now(checkout, state=state)


if __name__ == "__main__":
    sys.exit(main())
