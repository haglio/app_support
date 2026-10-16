"""Each production checkout kept at what has shipped, never while something of his runs from it.

``python -m app_support.production_update`` makes one pass over the checkouts
beside this one, and a scheduled task runs it every couple of minutes:
``--before-launch <checkout>`` brings one checkout up as a launcher is about to
start its app, so an app closed and opened again between two passes still opens
on what has shipped.

A checkout follows origin's default branch, or, when its pyproject says so, only
the commit a file of its own names.  Its libraries go in at exactly the versions
that commit pins, before its code, and neither moves while one of his programs
runs out of its venv, or out of the venv of a checkout that declares it starts
programs from this one.  An update holds ``.git/production-update.turn`` alone
for as long as it runs, and the launchers of a checkout that declares
``[tool.haglio.production]`` hold it shared while they start its app, so a launch
waits for an update rather than starting half way through one.

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import dataclasses
import logging
import os
import re
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from ctypes import wintypes
from pathlib import Path, PureWindowsPath

from app_support import json_store, processes
from app_support.dependencies import SiblingPin, sibling_pins_in
from app_support.logging_utils import configure_logging
from app_support.siblings import workspace_of
from app_support.subprocess_utils import hidden_subprocess_kwargs

TURN = "production-update.turn"
WAITING = "production-update.waiting"
# Where every launcher finds the interpreter that runs this module, from the
# folder holding the checkouts: this repo's own launcher runs out of it too.
UPDATER = r"app_support\.venv\Scripts\pythonw.exe"
ONE_PASS = "production_update.pass"
LOG_NAME = "production_update.log"
STATUS_NAME = "production_update.json"
# The mark a launcher of the machine's own upkeep puts on what it starts, so that
# a long-running checker can run out of a checkout's venv without holding back
# the update of the very checkout it checks.
UPKEEP_MARK = "HAGLIO_UPKEEP"
SCHEDULED_WAIT_S = 30.0
LAUNCH_WAIT_S = 15 * 60.0
RETRY_FAILED_AFTER_S = 30 * 60.0
GIT_TIMEOUT_S = 120.0
PIP_TIMEOUT_S = 15 * 60.0

_KEYS = frozenset({"commit-file", "also-runs"})
_log = logging.getLogger("production_update")


class ProductionSpecError(ValueError):
    pass


class StepFailed(Exception):
    pass


class Busy(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Declaration:
    commit_file: str | None = None
    also_runs: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Outcome:
    said: str
    at: float
    failed: bool = False
    target: str | None = None


Run = Callable[..., str]
InUse = Callable[[list[Path]], list[processes.Process]]


def declared(checkout: Path) -> Declaration | None:
    """What *checkout*'s pyproject tells the updater, or None when it says nothing.
    A checkout that declares the table at all has launchers that bring it up, and
    wait out an update of it, before they start its app."""
    try:
        text = (Path(checkout) / "pyproject.toml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    table = tomllib.loads(text).get("tool", {}).get("haglio", {}).get("production")
    if table is None:
        return None
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ProductionSpecError(f"[tool.haglio.production]: unknown key {', '.join(unknown)}")
    commit_file = table.get("commit-file")
    if commit_file is not None and not _inside_the_checkout(commit_file):
        raise ProductionSpecError(
            f"[tool.haglio.production]: commit-file {commit_file!r} must be a file inside the checkout")
    also_runs = table.get("also-runs", [])
    if not isinstance(also_runs, list) or not all(_a_folder_name(name) for name in also_runs):
        raise ProductionSpecError(
            f"[tool.haglio.production]: also-runs {also_runs!r} must name checkouts beside this one")
    return Declaration(commit_file, tuple(also_runs))


def _inside_the_checkout(path: object) -> bool:
    return (isinstance(path, str) and bool(path) and not PureWindowsPath(path).is_absolute()
            and ".." not in PureWindowsPath(path).parts)


def _a_folder_name(name: object) -> bool:
    return isinstance(name, str) and bool(name) and len(PureWindowsPath(name).parts) == 1 and name != ".."


# --- Running git and pip -------------------------------------------------------


def run(arguments: Sequence[str], *, cwd: Path | None = None, timeout: float = GIT_TIMEOUT_S) -> str:
    try:
        finished = subprocess.run(list(arguments), cwd=cwd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout,
                                  stdin=subprocess.DEVNULL, **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        raise StepFailed(f"{_step(arguments)} did not finish in {timeout:g} s") from None
    except OSError as cannot:
        raise StepFailed(f"{_step(arguments)} could not start: {cannot}") from None
    if finished.returncode != 0:
        said = " / ".join((finished.stderr or finished.stdout).strip().splitlines()[-3:])
        raise StepFailed(f"{_step(arguments)} said: {said or f'exit status {finished.returncode}'}")
    return finished.stdout


def _step(arguments: Sequence[str]) -> str:
    if "pip" in arguments:
        return "pip " + arguments[list(arguments).index("pip") + 1]
    return " ".join(arguments[:2])


def _git(checkout: Path, *arguments: str, run: Run) -> str:
    return run(["git", *arguments], cwd=checkout, timeout=GIT_TIMEOUT_S).strip()


def _git_or_none(checkout: Path, *arguments: str, run: Run) -> str | None:
    try:
        return _git(checkout, *arguments, run=run) or None
    except StepFailed:
        return None


def default_branch(checkout: Path, *, run: Run) -> str | None:
    head = _git_or_none(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run)
    if head and head.startswith("origin/"):
        return head[len("origin/"):]
    return next((name for name in ("main", "master")
                 if _git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", run=run)),
                None)


# --- The libraries a commit pins ----------------------------------------------


def _distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _release(version: str) -> tuple[int, ...]:
    found = re.match(r"v?(\d+(?:\.\d+)*)", version.strip())
    return tuple(int(part) for part in found.group(1).split(".")) if found else ()


def installed_versions(venv: Path) -> dict[str, str]:
    try:
        entries = os.listdir(Path(venv) / "Lib" / "site-packages")
    except OSError:
        return {}
    found = {}
    for entry in entries:
        if entry.endswith(".dist-info"):
            name, _, version = entry[: -len(".dist-info")].rpartition("-")
            if name:
                found[_distribution(name)] = version
    return found


def libraries_off_their_pins(pyproject_text: str, installed: Mapping[str, str]) -> list[SiblingPin]:
    return [pin for pin in sibling_pins_in(pyproject_text)
            if (have := installed.get(_distribution(pin.package))) is None
            or _release(have) != _release(pin.tag)]


# --- The turn ------------------------------------------------------------------


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


_READ_AND_WRITE, _SHARED_WITH_NOBODY, _OPEN_ALWAYS, _NORMAL = 0xC0000000, 0, 4, 0x80


def _held_alone(path: Path) -> int | None:
    handle = _kernel32().CreateFileW(str(path), _READ_AND_WRITE, _SHARED_WITH_NOBODY, None, _OPEN_ALWAYS,
                                     _NORMAL, None)
    return None if handle in (None, wintypes.HANDLE(-1).value) else handle


@contextlib.contextmanager
def _holding_alone(path: Path, *, wait_s: float, poll_s: float = 0.25):
    deadline = time.monotonic() + wait_s
    while (handle := _held_alone(path)) is None:
        if time.monotonic() >= deadline:
            raise Busy(f"{path} was held by another update or a launch for {wait_s:g} s")
        time.sleep(poll_s)
    try:
        yield
    finally:
        _kernel32().CloseHandle(handle)


def the_turn(checkout: Path, *, wait_s: float, poll_s: float = 0.25):
    return _holding_alone(Path(checkout) / ".git" / TURN, wait_s=wait_s, poll_s=poll_s)


def waits_for_programs_to_close(checkout: Path) -> bool:
    return (Path(checkout) / ".git" / WAITING).is_file()


# --- What runs from a venv -------------------------------------------------------


def _spelled(text: object) -> str:
    return str(text).replace("/", "\\").lower()


def running_from(venvs: Iterable[Path], *, whose=processes.whose_process) -> list[processes.Process]:
    """His programs running out of any of *venvs*: not an agent's, not one on a
    desktop of its own, not the machine's upkeep, and never this one or what
    started it."""
    marks = [_spelled(venv).rstrip("\\") + "\\" for venv in venvs]
    among = {process.pid: process for process in processes.running()}
    own = processes.this_process_and_its_parents(among)
    found = []
    for process in among.values():
        if process.pid in own or not any(mark in _spelled(f"{process.exe} {process.cmdline}") for mark in marks):
            continue
        if UPKEEP_MARK in processes.environment_names(process.pid):
            continue
        if whose(process, among) == processes.HIS:
            found.append(process)
    return found


def _venvs_watched(checkout: Path, workspace: Path) -> list[Path]:
    """This checkout's venv, and the venv of every checkout that starts programs out of it."""
    watched = [checkout / ".venv"]
    for other in checkouts_in(workspace):
        if other == checkout:
            continue
        with contextlib.suppress(ProductionSpecError, tomllib.TOMLDecodeError, OSError):
            if checkout.name.casefold() in (name.casefold() for name in _also_runs(other)):
                watched.append(other / ".venv")
    return watched


def _also_runs(checkout: Path) -> tuple[str, ...]:
    declaration = declared(checkout)
    return declaration.also_runs if declaration else ()


def checkouts_in(workspace: Path) -> list[Path]:
    return [entry for entry in sorted(Path(workspace).iterdir()) if (entry / ".git").is_dir()]


# --- Bringing one checkout up --------------------------------------------------------


class _LeftAlone(Exception):
    def __init__(self, said: str, *, failed: bool = False):
        super().__init__(said)
        self.failed = failed


@dataclasses.dataclass(frozen=True)
class _Plan:
    head: str
    target: str
    behind: bool
    libraries: list[SiblingPin]
    refusal: str | None = None

    @property
    def settled(self) -> str | None:
        """What to say when there is nothing to carry out."""
        if self.refusal or self.behind or self.libraries:
            return self.refusal
        return f"up to date at {self.head[:8]}"


def _branch_and_target(checkout: Path, *, run: Run) -> tuple[str, str]:
    branch = default_branch(checkout, run=run)
    if branch is None:
        raise _LeftAlone("follows no branch; left where it is")
    try:
        commit_file = (declared(checkout) or Declaration()).commit_file
    except (ProductionSpecError, tomllib.TOMLDecodeError) as wrong:
        raise _LeftAlone(f"failed: its pyproject: {wrong}", failed=True) from None
    if commit_file is None:
        target = _git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", run=run)
        missing = f"has no origin/{branch} to follow"
    else:
        try:
            named = (checkout / commit_file).read_text(encoding="utf-8").strip()
        except OSError:
            named = ""
        if not named:
            raise _LeftAlone(f"nothing has passed yet: {commit_file} names no commit")
        target = _git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"{named}^{{commit}}", run=run)
        missing = f"{commit_file} names {named[:8]}, which this checkout does not have"
    if target is None:
        raise _LeftAlone(missing)
    return branch, target


def _plan(checkout: Path, branch: str, target: str, *, run: Run) -> _Plan:
    head = _git(checkout, "rev-parse", "HEAD", run=run)
    on = _git_or_none(checkout, "symbolic-ref", "--quiet", "--short", "HEAD", run=run)
    if on != branch:
        return _Plan(head, target, False, [], f"is on {on or 'no branch'}, not {branch}; left where it is")
    behind = head != target and bool(_ancestor(checkout, head, target, run=run))
    if head != target and not behind and not _ancestor(checkout, target, head, run=run):
        return _Plan(head, target, False, [],
                     f"has commits {_describe(checkout, branch, target, run=run)} does not; left where it is")
    wanted = target if behind else head
    pyproject = _git_or_none(checkout, "show", f"{wanted}:pyproject.toml", run=run) or ""
    venv = checkout / ".venv"
    libraries = libraries_off_their_pins(pyproject, installed_versions(venv)) if venv.is_dir() else []
    if (behind or libraries) and _git(checkout, "status", "--porcelain", "--untracked-files=no", run=run):
        return _Plan(head, target, behind, libraries, "has uncommitted changes; left where it is")
    return _Plan(head, target, behind, libraries)


def _ancestor(checkout: Path, older: str, newer: str, *, run: Run) -> bool:
    try:
        _git(checkout, "merge-base", "--is-ancestor", older, newer, run=run)
    except StepFailed:
        return False
    return True


def _describe(checkout: Path, branch: str, target: str, *, run: Run) -> str:
    tracking = _git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", run=run)
    return f"origin/{branch}" if tracking == target else target[:8]


def _carry_out(checkout: Path, plan: _Plan, *, run: Run) -> str:
    python = checkout / ".venv" / "Scripts" / "python.exe"
    done = []
    if plan.libraries:
        run([str(python), "-m", "pip", "install", *(pin.spec for pin in plan.libraries)], cwd=checkout,
            timeout=PIP_TIMEOUT_S)
        done.append("installed " + ", ".join(f"{pin.package} {pin.tag}" for pin in plan.libraries))
    changed = []
    if plan.behind:
        changed = _git(checkout, "diff", "--name-only", plan.head, plan.target, run=run).splitlines()
        _git(checkout, "merge", "--ff-only", "--quiet", plan.target, run=run)
        done.insert(0, f"moved from {plan.head[:8]} to {plan.target[:8]}")
    if (checkout / ".venv").is_dir() and (plan.libraries or "pyproject.toml" in changed):
        run([str(python), "-m", "pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"],
            cwd=checkout, timeout=PIP_TIMEOUT_S)
    return "; ".join(done)


def bring_up(checkout: Path, *, workspace: Path, run: Run = run, wait_s: float = SCHEDULED_WAIT_S,
             in_use: InUse = running_from, previous: Outcome | None = None,
             now: Callable[[], float] = time.time) -> Outcome:
    checkout, target = Path(checkout), None
    try:
        branch, target = _branch_and_target(checkout, run=run)
        if (previous is not None and previous.failed and previous.target == target
                and now() - previous.at < RETRY_FAILED_AFTER_S):
            return previous
        said = _bring_up_to(checkout, branch, target, workspace=workspace, run=run, wait_s=wait_s, in_use=in_use)
        return Outcome(said, now(), False, target)
    except _LeftAlone as left:
        return Outcome(_not_waiting(checkout, str(left)), now(), left.failed, target)
    except Busy as busy:
        return Outcome(f"busy: {busy}", now(), False, target)
    except StepFailed as failed:
        return Outcome(f"failed: {failed}", now(), True, target)


def _bring_up_to(checkout: Path, branch: str, target: str, *, workspace: Path, run: Run, wait_s: float,
                 in_use: InUse) -> str:
    settled = _plan(checkout, branch, target, run=run).settled
    if settled:
        return _not_waiting(checkout, settled)
    with the_turn(checkout, wait_s=wait_s):
        plan = _plan(checkout, branch, target, run=run)
        if plan.settled:
            return _not_waiting(checkout, plan.settled)
        if running := in_use(_venvs_watched(checkout, workspace)):
            return _waiting_for(checkout, running)
        return _not_waiting(checkout, _carry_out(checkout, plan, run=run))


def _waiting_for(checkout: Path, running: list[processes.Process]) -> str:
    said = f"waiting for {', '.join(sorted({process.name for process in running}))} to close"
    (checkout / ".git" / WAITING).write_text(said + "\n", encoding="utf-8")
    return said


def _not_waiting(checkout: Path, said: str) -> str:
    (checkout / ".git" / WAITING).unlink(missing_ok=True)
    return said


# --- A pass, and a launch ---------------------------------------------------------


def _previous(state: Path) -> dict[str, Outcome]:
    try:
        recorded = json_store.read_json(state / STATUS_NAME).get("checkouts", {})
    except (OSError, ValueError):
        return {}
    return {name: Outcome(**entry) for name, entry in recorded.items()
            if isinstance(entry, dict) and set(entry) == {field.name for field in dataclasses.fields(Outcome)}}


def _record(state: Path, outcomes: Mapping[str, Outcome], previous: Mapping[str, Outcome], *,
            finished: float | None = None) -> None:
    for name, outcome in outcomes.items():
        if outcome.said != getattr(previous.get(name), "said", None):
            (_log.warning if outcome.failed else _log.info)("%s: %s", name, outcome.said)

    def update(document: dict) -> dict:
        document.setdefault("checkouts", {}).update(
            {name: dataclasses.asdict(outcome) for name, outcome in outcomes.items()})
        if finished is not None:
            document["pass_finished"] = finished
        return document

    json_store.locked_update(state / STATUS_NAME, update)


def keep_up(workspace: Path, state: Path, *, fetch: bool = True, run: Run = run,
            wait_s: float = SCHEDULED_WAIT_S, in_use: InUse = running_from,
            now: Callable[[], float] = time.time) -> dict[str, Outcome]:
    previous = _previous(state)
    outcomes = {}
    for checkout in checkouts_in(workspace):
        branch = default_branch(checkout, run=run)
        if fetch and branch:
            try:
                _git(checkout, "fetch", "--quiet", "origin", branch, run=run)
            except StepFailed as unreachable:
                _log.warning("%s: could not fetch: %s", checkout.name, unreachable)
        outcomes[checkout.name] = bring_up(checkout, workspace=workspace, run=run, wait_s=wait_s,
                                           in_use=in_use, previous=previous.get(checkout.name), now=now)
    _record(state, outcomes, previous, finished=now())
    return outcomes


def before_launch(checkout: Path, workspace: Path, state: Path, *, run: Run = run,
                  wait_s: float = LAUNCH_WAIT_S, in_use: InUse = running_from,
                  now: Callable[[], float] = time.time) -> dict[str, Outcome]:
    previous = _previous(state)
    checkout = Path(checkout)
    try:
        also_runs = _also_runs(checkout)
    except (ProductionSpecError, tomllib.TOMLDecodeError):
        also_runs = ()
    started_by_it = [checkout, *(Path(workspace) / name for name in also_runs)]
    outcomes = {each.name: bring_up(each, workspace=workspace, run=run, wait_s=wait_s, in_use=in_use,
                                    previous=previous.get(each.name), now=now)
                for each in started_by_it if (each / ".git").is_dir()}
    _record(state, outcomes, previous)
    return outcomes


def main(argv: list[str] | None = None, *, run: Run = run, in_use: InUse = running_from) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app_support.production_update",
        description="Bring every production checkout beside this one up to what has shipped, "
                    "never while something of his runs out of it.")
    parser.add_argument("--before-launch", type=Path, metavar="CHECKOUT",
                        help="bring this checkout, and what it starts programs from, up before its app starts")
    parser.add_argument("--workspace", type=Path, help="the folder holding the checkouts")
    parser.add_argument("--state", type=Path, help="where the log and the record of each checkout go")
    options = parser.parse_args(argv)
    here = Path(__file__).resolve()
    state = options.state or here.parents[1] / "state"
    configure_logging("production_update", state / LOG_NAME)
    if options.before_launch:
        checkout = options.before_launch.resolve()
        before_launch(checkout, options.workspace or checkout.parent, state, run=run, in_use=in_use)
        return 0
    with contextlib.suppress(Busy), _holding_alone(state / ONE_PASS, wait_s=0):
        keep_up(options.workspace or workspace_of(here), state, run=run, in_use=in_use)
    return 0


if __name__ == "__main__":
    sys.exit(main())
