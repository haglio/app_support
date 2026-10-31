"""``python -m app_support.hotfix``, run from an agent's worktree: its branch's fix into production now.

From an app's worktree the fix goes to that app's production, with the shared code's fixes ``--with``
names; from a worktree of the shared code it goes to every app whose production runs that code, as a
version tagged here and never pushed. Production's updater keeps a hotfix until the same fix ships the
usual way, or until ``--take-back`` sends it back to what has shipped. Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fnmatch
import functools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath

from app_support import import_sweep, production_update
from app_support.dependencies import SiblingPin, repinned, sibling_pins_in
from app_support.logging_utils import configure_logging
from app_support.production_update import (
    HOTFIX_REF,
    InUse,
    Original,
    Outcome,
    Run,
    StepFailed,
    git,
    git_or_none,
    hotfix_message,
    is_ancestor,
)
from app_support.subprocess_utils import hidden_subprocess_kwargs, run_process_tree

CHECKS_TIMEOUT_S = 10 * 60.0
NOTHING_ASKED_FOR = "0" * 40
_RELEASE = re.compile(r"v\d+\.\d+\.\d+")
Check = Callable[[Path, list[str], Path, list[Path]], None]
Sweep = Callable[[Path, Path, list[Path]], None]
BringUp = Callable[[Path], Outcome]


class Refused(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class _Fix:
    worktree: Path
    production: Path
    shipped: str
    tip: str
    originals: tuple[tuple[str, int], ...]
    subject: str
    changed: tuple[str, ...]

    @property
    def repo(self) -> str:
        return self.production.name


@dataclasses.dataclass
class _SharedHotfix:
    fix: _Fix
    place: Path
    commit: str
    tag: str
    brought_along: int
    tagged: bool = False


def hotfix(worktree: Path, *, libraries: Sequence[Path] = (), run: Run = production_update.run, check: Check,
           sweep: Sweep, bring_up: BringUp) -> str:
    fix = _a_fix(Path(worktree), run=run)
    shared = [_a_fix(Path(library), run=run) for library in libraries]
    app_fix = fix if _names_checks(fix.worktree) else None
    if app_fix is None:
        shared = [fix, *shared]
    apps = _apps_reached_from(fix.worktree, fix.production, {each.repo for each in shared})
    built: dict[tuple[str, str], _SharedHotfix] = {}
    with contextlib.ExitStack() as shared_places:
        return _in_each(apps, "took the hotfix", lambda app: _hotfix_of(
            app, app_fix, shared, built, shared_places, run=run, check=check, sweep=sweep, bring_up=bring_up))


def take_back(worktree: Path, *, run: Run = production_update.run, bring_up: BringUp) -> str:
    worktree = _top_of(Path(worktree), run=run)
    production = _production_of(worktree, run=run)
    apps = _apps_reached_from(worktree, production, {production.name})
    return _in_each(apps, "went back", lambda app: _taken_back_from(app, run=run, bring_up=bring_up))


def _apps_reached_from(worktree: Path, production: Path, shared_repos: set[str]) -> list[Path]:
    if _names_checks(worktree):
        return [production]
    apps = [checkout for checkout in production_update.checkouts_in(production.parent)
            if _names_checks(checkout) and _pins_any_of(checkout, shared_repos)]
    if not apps:
        raise Refused(f"{production.name} names no checks in [tool.haglio.hotfix], and no app that does runs it, "
                      f"so its fixes ship the usual way")
    return apps


def _in_each(apps: list[Path], what_every_app_did: str, do: Callable[[Path], str]) -> str:
    said, refused = [], False
    for app in apps:
        try:
            said.append(do(app))
        except (Refused, StepFailed) as refusal:
            if len(apps) == 1:
                raise
            said.append(f"production {app.name} refused it: {refusal}")
            refused = True
    if refused:
        raise Refused(f"not every app {what_every_app_did}:\n" + "\n".join(said))
    return "\n".join(said)


def _taken_back_from(app: Path, *, run: Run, bring_up: BringUp) -> str:
    if not production_update.take_back(app, run=run):
        return f"production {app.name} runs no hotfix"
    outcome = bring_up(app)
    if not production_update.runs_a_hotfix(app, run=run):
        return f"production {app.name} runs what has shipped ({git(app, 'rev-parse', 'HEAD', run=run)[:8]})"
    if production_update.waits_for_programs_to_close(app):
        return f"production {app.name} goes back to what has shipped once its app closes ({outcome.said})"
    raise Refused(f"production {app.name} did not go back to what has shipped: {outcome.said}")


def _top_of(worktree: Path, *, run: Run) -> Path:
    return Path(git(worktree, "rev-parse", "--show-toplevel", run=run))


def _production_of(worktree: Path, *, run: Run) -> Path:
    return Path(git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir", run=run)).parent


def _a_fix(worktree: Path, *, run: Run) -> _Fix:
    worktree = _top_of(worktree, run=run)
    if production_update.uncommitted_changes(worktree, run=run):
        raise Refused(f"{worktree} has uncommitted changes; commit the fix first")
    production = _production_of(worktree, run=run)
    shipped = f"refs/remotes/origin/{production_update.default_branch(production, run=run)}"
    tip = git(worktree, "rev-parse", "HEAD", run=run)
    commits = [line.split("\x1f") for line in git(
        worktree, "log", "--reverse", "--format=%ae%x1f%at%x1f%s", f"{shipped}..{tip}", run=run).splitlines()]
    if not commits:
        raise Refused(f"{worktree} has nothing {shipped.removeprefix('refs/remotes/')} lacks")
    changed = git(worktree, "diff", "--name-only", f"{shipped}...{tip}", run=run).splitlines()
    return _Fix(worktree, production, shipped, tip, tuple((email, int(seconds)) for email, seconds, _ in commits),
                commits[0][2], tuple(changed))


def _hotfix_checks(pyproject_text: str) -> list[str]:
    return list(tomllib.loads(pyproject_text).get("tool", {}).get("haglio", {}).get("hotfix", {}).get("checks", []))


def _names_checks(checkout: Path) -> bool:
    try:
        return bool(_hotfix_checks((checkout / "pyproject.toml").read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        return False


def _pins_any_of(checkout: Path, repos: set[str]) -> bool:
    return bool(repos & {pin.repo for pin in sibling_pins_in((checkout / "pyproject.toml").read_text(encoding="utf-8"))})


def _hotfix_of(app: Path, app_fix: _Fix | None, shared: list[_Fix], built: dict[tuple[str, str], _SharedHotfix],
               shared_places: contextlib.ExitStack, *, run: Run, check: Check, sweep: Sweep, bring_up: BringUp) -> str:
    base = production_update.heading_for(app, run=run)
    asked_before = _asked_for(app, run=run)
    with contextlib.ExitStack() as this_app:
        place, brought_along = _the_app_hotfix(app, base, app_fix, this_app, run=run)
        pyproject = place / "pyproject.toml"
        pins = {pin.repo: pin for pin in sibling_pins_in(pyproject.read_text(encoding="utf-8"))}
        if app_fix and (unpinned := [fix.repo for fix in shared if fix.repo not in pins]):
            raise Refused(f"production {app.name} does not run {', '.join(unpinned)}")
        hotfixes = [_the_shared_hotfix(fix, pins[fix.repo].tag, built, shared_places, run=run)
                    for fix in shared if fix.repo in pins]
        for each in hotfixes:
            _repin(pyproject, pins[each.fix.repo], each.tag)
        made = _commit(place, app_fix, hotfixes, run=run)
        python = app / ".venv" / "Scripts" / "python.exe"
        pythonpath = [each.place for each in hotfixes] + _versions_the_venv_lacks(app, pyproject, hotfixes, this_app,
                                                                                  run=run)
        check(python, _checks(place, app_fix.changed if app_fix else ()), place, pythonpath)
        for each in hotfixes:
            if tests := _tests_the_suite_runs(each.place, each.fix.changed):
                check(python, tests, each.place, pythonpath)
        sweep(python, place, pythonpath)
        for each in hotfixes:
            _tag(each, run=run)
        _ask_for(app, made, asked_before, run=run)
    return _what_production_did(app, made, bring_up(app), run=run) + _what_else_it_brings(brought_along, hotfixes)


def _ask_for(production: Path, made: str, asked_before: str, *, run: Run) -> None:
    try:
        git(production, "update-ref", HOTFIX_REF, made, asked_before, run=run)
    except StepFailed:
        if git(production, "rev-parse", "HEAD", run=run) != asked_before:
            raise Refused("another hotfix was asked for while this one was being made; run the route again, "
                          "and it builds on that one") from None
        _ask_for(production, made, NOTHING_ASKED_FOR, run=run)


def _the_app_hotfix(app: Path, base: str, app_fix: _Fix | None, stack: contextlib.ExitStack, *,
                    run: Run) -> tuple[Path, int]:
    if app_fix is None:
        return _checked_out(app, base, stack, run=run), 0
    return _with_the_fix(app, app_fix, base, stack, run=run)


def _the_shared_hotfix(fix: _Fix, pinned: str, built: dict[tuple[str, str], _SharedHotfix],
                       shared_places: contextlib.ExitStack, *, run: Run) -> _SharedHotfix:
    library = fix.production
    if (fix.repo, pinned) not in built:
        with contextlib.ExitStack() as attempt:
            place, brought_along = _with_the_fix(library, fix, pinned, attempt, run=run)
            on = git(place, "rev-parse", "HEAD", run=run)
            if (fix.repo, on) not in built:
                git(place, "commit", "-q", "--no-verify", "-m", hotfix_message(fix.subject, fix.originals), run=run)
                built[fix.repo, on] = _SharedHotfix(fix, place, git(place, "rev-parse", "HEAD", run=run),
                                                    _next_tag(library, on, run=run), brought_along)
                shared_places.enter_context(attempt.pop_all())
        built[fix.repo, pinned] = built[fix.repo, on]
    return built[fix.repo, pinned]


def _with_the_fix(repository: Path, fix: _Fix, made_on: str, stack: contextlib.ExitStack, *,
                  run: Run) -> tuple[Path, int]:
    base, main = _the_commit(repository, made_on, run=run), git(repository, "rev-parse", fix.shipped, run=run)
    bases = [base, main] if base != main and is_ancestor(repository, base, main, run=run) else [base]
    clashing: set[str] = set()
    for each in bases:
        with contextlib.ExitStack() as attempt:
            place = _checked_out(repository, each, attempt, run=run)
            patch = place.parent / "fix.patch"
            git(fix.worktree, "diff", "--binary", f"--output={patch}", f"{fix.shipped}...{fix.tip}", run=run)
            try:
                git(place, "apply", "--3way", "--index", str(patch), run=run)
            except StepFailed as failed:
                clashing.update(git(place, "diff", "--name-only", "--diff-filter=U", run=run).split() or [str(failed)])
                continue
            stack.enter_context(attempt.pop_all())
            return place, _commits_between(repository, base, each, run=run)
    raise Refused(f"the fix in {fix.repo} clashes with what production runs" + (" and with main" if len(bases) > 1 else "")
                  + f" ({', '.join(sorted(clashing))}); rebase it onto main and run the route again")


def _checked_out(repository: Path, revision: str, stack: contextlib.ExitStack, *, run: Run) -> Path:
    commit = _the_commit(repository, revision, run=run)
    room = Path(tempfile.mkdtemp(prefix="hotfix-"))
    stack.callback(shutil.rmtree, room, ignore_errors=True)
    place = room / repository.name
    git(repository, "worktree", "add", "--detach", str(place), commit, run=run)
    stack.callback(_removed, repository, place, run)
    return place


def _removed(repository: Path, place: Path, run: Run) -> None:
    with contextlib.suppress(StepFailed):
        git(repository, "worktree", "remove", "--force", str(place), run=run)


def _the_commit(repository: Path, revision: str, *, run: Run) -> str:
    if found := _resolved(repository, revision, run=run):
        return found
    with contextlib.suppress(StepFailed):
        git(repository, "fetch", "--quiet", "origin", f"refs/tags/{revision}:refs/tags/{revision}", run=run)
    if found := _resolved(repository, revision, run=run):
        return found
    raise Refused(f"{repository.name} has no {revision}, here or on GitHub")


def _resolved(repository: Path, revision: str, *, run: Run) -> str | None:
    return git_or_none(repository, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", run=run)


def _commits_between(repository: Path, older: str, newer: str, *, run: Run) -> int:
    return int(git(repository, "rev-list", "--count", f"{older}..{newer}", run=run))


def _next_tag(library: Path, on: str, *, run: Run) -> str:
    release = _RELEASE.match(git(library, "describe", "--tags", "--abbrev=0", on, run=run)).group()
    numbers = [tag.removeprefix(f"{release}.") for tag in git(library, "tag", "--list", f"{release}.*",
                                                               run=run).split()]
    return f"{release}.{max((int(number) for number in numbers if number.isdigit()), default=0) + 1}"


def _tag(shared_hotfix: _SharedHotfix, *, run: Run) -> None:
    if not shared_hotfix.tagged:
        try:
            git(shared_hotfix.fix.production, "tag", shared_hotfix.tag, shared_hotfix.commit, run=run)
        except StepFailed:
            raise Refused(f"another hotfix took {shared_hotfix.fix.repo} {shared_hotfix.tag} meanwhile; run the "
                          f"route again") from None
        shared_hotfix.tagged = True


def _repin(pyproject: Path, pin: SiblingPin, tag: str) -> None:
    pyproject.write_bytes(repinned(pyproject.read_bytes().decode("utf-8"), pin, tag).encode("utf-8"))


def _commit(place: Path, app_fix: _Fix | None, hotfixes: list[_SharedHotfix], *, run: Run) -> str:
    originals = [Original(email, seconds) for email, seconds in (app_fix.originals if app_fix else ())]
    originals += [Original(email, seconds, each.fix.repo) for each in hotfixes for email, seconds in each.fix.originals]
    subject = app_fix.subject if app_fix else f"{hotfixes[0].fix.subject} ({hotfixes[0].fix.repo} {hotfixes[0].tag})"
    git(place, "add", "pyproject.toml", run=run)
    git(place, "commit", "-q", "--no-verify", "-m", hotfix_message(subject, originals), run=run)
    return git(place, "rev-parse", "HEAD", run=run)


def _versions_the_venv_lacks(app: Path, pyproject: Path, hotfixes: list[_SharedHotfix], stack: contextlib.ExitStack,
                             *, run: Run) -> list[Path]:
    hotfixed = {each.fix.repo for each in hotfixes}
    lacking = production_update.libraries_off_their_pins(pyproject.read_text(encoding="utf-8"),
                                                         production_update.installed_versions(app / ".venv"))
    return [_checked_out(app.parent / pin.repo, pin.tag, stack, run=run) for pin in lacking
            if pin.repo not in hotfixed]


def _what_production_did(production: Path, made: str, outcome: Outcome, *, run: Run) -> str:
    if git(production, "rev-parse", "HEAD", run=run) == made:
        return f"production {production.name} runs the hotfix {made[:8]} now" + (
            f", but {outcome.said}" if outcome.failed else "")
    if production_update.waits_for_programs_to_close(production):
        return f"production {production.name} takes the hotfix {made[:8]} once its app closes ({outcome.said})"
    with contextlib.suppress(StepFailed):
        git(production, "update-ref", "-d", HOTFIX_REF, made, run=run)
    raise Refused(f"production {production.name} did not take the hotfix {made[:8]}: {outcome.said}")


def _what_else_it_brings(app_changes: int, hotfixes: list[_SharedHotfix]) -> str:
    brought = [(f"{_changes(app_changes)} that shipped but {'has' if app_changes == 1 else 'have'} not passed the "
                f"main verifier yet")] if app_changes else []
    brought += [f"{_changes(each.brought_along)} to {each.fix.repo} since the version production runs"
                for each in hotfixes if each.brought_along]
    return f"; it also brings along {' and '.join(brought)}" if brought else ""


def _changes(count: int) -> str:
    return f"{count} change" + ("" if count == 1 else "s")


def _asked_for(production: Path, *, run: Run) -> str:
    try:
        return git(production, "rev-parse", "--verify", "--quiet", HOTFIX_REF, run=run)
    except StepFailed:
        return NOTHING_ASKED_FOR


def _checks(place: Path, changed: Sequence[str]) -> list[str]:
    named = _hotfix_checks((place / "pyproject.toml").read_text(encoding="utf-8"))
    return named + [test for test in _tests_the_suite_runs(place, changed) if test not in named]


def _tests_the_suite_runs(place: Path, changed: Sequence[str]) -> list[str]:
    collected = tomllib.loads((place / "pyproject.toml").read_text(encoding="utf-8")).get("tool", {}).get(
        "pytest", {}).get("ini_options", {})
    return [path for path in changed if (place / path).is_file()
            and _a_test_the_suite_runs(PurePosixPath(path), collected.get("testpaths"),
                                       collected.get("norecursedirs", []))]


def _a_test_the_suite_runs(path: PurePosixPath, roots: list[str] | None, passed_over: list[str]) -> bool:
    return (path.name.startswith("test_") and path.suffix == ".py"
            and (roots is None or any(path.is_relative_to(root) for root in roots))
            and not any(fnmatch.fnmatch(folder, pattern) for folder in path.parent.parts for pattern in passed_over))


def _environment_with(pythonpath: Sequence[Path]) -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    if pythonpath:
        environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in pythonpath)
    return environment


def run_checks(python: Path, tests: list[str], place: Path, pythonpath: Sequence[Path]) -> None:
    command = [str(python), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests]
    try:
        finished = run_process_tree(command, cwd=place, text=True, encoding="utf-8", errors="replace",
                                    timeout=CHECKS_TIMEOUT_S, stdin=subprocess.DEVNULL,
                                    env=_environment_with(pythonpath), **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        raise Refused(f"the checks did not finish in {CHECKS_TIMEOUT_S / 60:g} minutes") from None
    if finished.returncode != 0:
        said = (finished.stdout + finished.stderr).strip().splitlines()[-12:]
        raise Refused("a check failed:\n" + "\n".join(said))


def run_sweep(python: Path, place: Path, pythonpath: Sequence[Path]) -> None:
    failures = import_sweep.sweep(place, python=str(python), env=_environment_with(pythonpath)).failures
    if failures:
        module, failure = next(iter(failures.items()))
        others = f", nor did {len(failures) - 1} more" if len(failures) > 1 else ""
        raise Refused(f"{module} did not import{others}:\n{failure.strip()}")


def bring_up_now(checkout: Path, *, state: Path, in_use: InUse = production_update.running_from) -> Outcome:
    return production_update.before_launch(checkout, checkout.parent, state, in_use=in_use)[checkout.name]


def main(argv: Sequence[str] | None = None, *, state: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app_support.hotfix", description=__doc__.splitlines()[0])
    parser.add_argument("--with", dest="libraries", action="append", type=Path, default=[], metavar="WORKTREE",
                        help="a worktree of the shared code this fix needs, to go out with it")
    parser.add_argument("--take-back", action="store_true",
                        help="take every hotfix back out of production, which then runs what has shipped")
    options = parser.parse_args(argv)
    bring_up = functools.partial(_logged_bring_up, state=state or Path(production_update.__file__).resolve().parents[1]
                                 / "state")
    try:
        if options.take_back:
            print(take_back(Path.cwd(), bring_up=bring_up))
        else:
            print(hotfix(Path.cwd(), libraries=options.libraries, check=run_checks, sweep=run_sweep,
                         bring_up=bring_up))
    except (Refused, StepFailed) as refused:
        print(f"refused: {refused}")
        return 1
    return 0


def _logged_bring_up(checkout: Path, state: Path) -> Outcome:
    configure_logging("production_update", state / production_update.LOG_NAME)
    return bring_up_now(checkout, state=state)


if __name__ == "__main__":
    sys.exit(main())
