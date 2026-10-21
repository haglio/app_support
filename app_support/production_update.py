"""Each production checkout kept at what has shipped, never while something of his runs from it.

``python -m app_support.production_update`` makes one pass over the checkouts
beside this one, and a scheduled task runs it every couple of minutes:
``--before-launch <checkout>`` brings one checkout up as a launcher is about to
start its app, so an app closed and opened again between two passes still opens
on what has shipped.  A pass asks GitHub once what every checkout's main is and
fetches only the checkouts whose main moved, so the machine's agents are not
competing with it for GitHub; a checkout the answer leaves out is fetched once
its last fetch is half an hour old.

A checkout follows origin's default branch, or, when the pyproject on that branch
says so, only the commit a file of its own names.  A hotfix asked for at ``refs/haglio/hotfix``
goes ahead of either, and the checkout keeps it until the same fix ships the usual way.  Its libraries go in at exactly the versions
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
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from ctypes import wintypes
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

from app_support import json_store, processes, win32
from app_support.dependencies import SiblingPin, sibling_pins_in
from app_support.file_channel import publish_whole
from app_support.logging_utils import configure_logging
from app_support.siblings import workspace_of
from app_support.subprocess_utils import hidden_subprocess_kwargs

TURN = "production-update.turn"
WAITING = "production-update.waiting"
PROGRESS = "production-update.progress"
# Where every launcher finds the interpreter that runs this module, from the
# folder holding the checkouts: this repo's own launcher runs out of it too.
UPDATER = r"app_support\.venv\Scripts\pythonw.exe"
HOTFIX_REF = "refs/haglio/hotfix"
HOTFIX_OF = "Hotfix-of"
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
HOTFIX_SHIPS_WITHIN_S = 24 * 60 * 60.0
FETCH_UNASKED_AFTER_S = 30 * 60.0
GITHUB_ANSWERS = "answers what has shipped again, so only a checkout whose main moved is fetched"
# The Claude app fast-forwards the checked-out main of a project it starts a session in, and its
# preflight passes over a checkout while that checkout's info/attributes holds any rule.
HANDS_OFF_RULE = "/.moved-only-by-the-production-updater moved-only-by-the-production-updater"
UP_BEFORE_AN_UPDATE_S = 10 * 60.0
GIT_TIMEOUT_S = 120.0
PIP_TIMEOUT_S = 15 * 60.0
# How long each step of an update usually takes, so that a loading screen
# waiting on one can move its bar: a library comes from GitHub as a clone.
LIBRARY_S = 15.0
MOVE_S = 2.0
REINSTALL_S = 10.0

_KEYS = frozenset({"commit-file", "also-runs"})
_STANDS_FOR = re.compile(rf"^{HOTFIX_OF}: (\S+) (\d+)(?: in (\S+))?$", re.MULTILINE)
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{40})")
_FIELD, _RECORD = "\x1f", "\x1e"
_ON_GITHUB = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$", re.IGNORECASE)
_HEADS_QUERY = ("query($owner: String!) { repositoryOwner(login: $owner) { repositories(first: 100, "
                "orderBy: {field: PUSHED_AT, direction: DESC}) { nodes { name defaultBranchRef "
                "{ name target { oid } } } } } }")
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
class UpdateProgress:
    steps: tuple[tuple[str, float], ...]
    step: int
    since: float
    pid: int
    started: int | None

    def fraction(self, *, now: float) -> float:
        seconds = [usual for _name, usual in self.steps]
        under_way = seconds[self.step]
        gone_by = 1 - math.exp(-max(0.0, now - self.since) / under_way)
        return (sum(seconds[:self.step]) + under_way * gone_by) / sum(seconds)


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
    return _declared_in(text)


def _declared_in(pyproject_text: str) -> Declaration | None:
    table = tomllib.loads(pyproject_text).get("tool", {}).get("haglio", {}).get("production")
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


def run(arguments: Sequence[str], *, cwd: Path | None = None, timeout: float = GIT_TIMEOUT_S,
        env: Mapping[str, str] | None = None) -> str:
    try:
        finished = subprocess.run(list(arguments), cwd=cwd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout,
                                  env={**os.environ, **env} if env else None,
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


def default_branch(checkout: Path, *, run: Run) -> str | None:
    head = git_or_none(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", run=run)
    if head and head.startswith("origin/"):
        return head[len("origin/"):]
    return next((name for name in ("main", "master")
                 if git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", run=run)),
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


class UpdateWatch:
    def __init__(self, checkout: Path, *, a_good_moment: Callable[[], bool], start_again: Callable[[], None],
                 logger: logging.Logger, clock: Callable[[], float] = time.monotonic):
        self._checkout = Path(checkout)
        self._a_good_moment = a_good_moment
        self._start_again = start_again
        self._logger = logger
        self._clock = clock
        self._up_since = clock()

    def tick(self) -> None:
        if (self._clock() - self._up_since >= UP_BEFORE_AN_UPDATE_S
                and self._a_good_moment() and waits_for_programs_to_close(self._checkout)):
            self._logger.info("An update of %s is waiting for this app to close; "
                              "starting it again to take the update", self._checkout)
            self._start_again()


_THEN_THE_LAUNCHER = """\
import ctypes, subprocess, sys
kernel32 = ctypes.WinDLL("kernel32")
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
ending = kernel32.OpenProcess(0x00100000, False, int(sys.argv[1]))
if ending:
    kernel32.WaitForSingleObject(ending, 120000)
subprocess.run(["wscript.exe", sys.argv[2]])
"""


def start_again_after(pid: int, launcher: Path, *, popen=subprocess.Popen) -> None:
    """Run *launcher* once the process *pid* has ended, from the plain interpreter:
    its catch-up updates the checkout only while nothing runs out of the venv."""
    popen([str(Path(sys._base_executable).with_name("pythonw.exe")), "-c", _THEN_THE_LAUNCHER,
           str(pid), str(launcher)],
          creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


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
    moves: bool
    libraries: list[SiblingPin]
    refusal: str | None = None
    failed: bool = False

    @property
    def settled(self) -> str | None:
        """What to say when there is nothing to carry out."""
        if self.refusal or self.moves or self.libraries:
            return self.refusal
        return f"up to date at {self.head[:8]}"


def _branch_and_target(checkout: Path, *, run: Run) -> tuple[str, str]:
    branch = default_branch(checkout, run=run)
    if branch is None:
        raise _LeftAlone("follows no branch; left where it is")
    shipped = git_or_none(checkout, "show", f"refs/remotes/origin/{branch}:pyproject.toml", run=run) or ""
    try:
        commit_file = (_declared_in(shipped) or Declaration()).commit_file
    except (ProductionSpecError, tomllib.TOMLDecodeError) as wrong:
        raise _LeftAlone(f"failed: the pyproject on origin/{branch}: {wrong}", failed=True) from None
    if commit_file is None:
        target = git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", run=run)
        missing = f"has no origin/{branch} to follow"
    else:
        try:
            named = (checkout / commit_file).read_text(encoding="utf-8").strip()
        except OSError:
            named = ""
        if not named:
            raise _LeftAlone(f"nothing has passed yet: {commit_file} names no commit")
        target = git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"{named}^{{commit}}", run=run)
        missing = f"{commit_file} names {named[:8]}, which this checkout does not have"
    if target is None:
        raise _LeftAlone(missing)
    return branch, _the_hotfix_or(checkout, target, run=run)


def _the_hotfix_or(checkout: Path, target: str, *, run: Run) -> str:
    hotfix = git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"{HOTFIX_REF}^{{commit}}", run=run)
    if hotfix is None:
        return target
    head = git(checkout, "rev-parse", "HEAD", run=run)
    if hotfix != head:
        if any(is_ancestor(checkout, made_on, hotfix, run=run) for made_on in (head, target)):
            return hotfix
        _log.warning("%s: left out the hotfix %s, made on a commit it has moved past", checkout.name, hotfix[:8])
    git(checkout, "update-ref", "-d", HOTFIX_REF, run=run)
    return target


def _plan(checkout: Path, branch: str, target: str, *, workspace: Path, run: Run, now: Callable[[], float]) -> _Plan:
    head = git(checkout, "rev-parse", "HEAD", run=run)
    on = git_or_none(checkout, "symbolic-ref", "--quiet", "--short", "HEAD", run=run)
    if on != branch:
        return _Plan(head, target, False, [], f"is on {on or 'no branch'}, not {branch}; left where it is")
    moves = head != target and bool(is_ancestor(checkout, head, target, run=run))
    if head != target and not moves:
        if hotfixes := _hotfixes_on(checkout, branch, head, run=run):
            if unshipped := [hotfix for hotfix in hotfixes
                             if not _has_shipped(hotfix, checkout, workspace, head, target, run=run)]:
                return _kept_at_its_hotfix(head, target, unshipped, now=now)
            moves = not is_ancestor(checkout, target, head, run=run)
        elif not is_ancestor(checkout, target, head, run=run):
            return _Plan(head, target, False, [],
                         f"has commits {_describe(checkout, branch, target, run=run)} does not; left where it is")
    libraries = _libraries_off(checkout, target if moves else head, run=run)
    if (moves or libraries) and git(checkout, "status", "--porcelain", "--untracked-files=no", run=run):
        return _Plan(head, target, moves, libraries, "has uncommitted changes; left where it is")
    return _Plan(head, target, moves, libraries)


class Original(NamedTuple):
    email: str
    seconds: int
    repo: str = ""


def hotfix_message(subject: str, originals: Iterable[tuple]) -> str:
    lines = [f"{HOTFIX_OF}: {original.email} {original.seconds}" + (f" in {original.repo}" if original.repo else "")
             for original in (Original(*each) for each in originals)]
    return subject + "\n\n" + "".join(line + "\n" for line in lines)


@dataclasses.dataclass(frozen=True)
class _Hotfix:
    commit: str
    subject: str
    made: int
    originals: frozenset[tuple[str, str, str]]


def _commits(checkout: Path, span: str, *fields: str, run: Run) -> list[list[str]]:
    listed = git(checkout, "log", "--format=" + _FIELD.join(fields) + _RECORD, span, run=run)
    return [record.strip().split(_FIELD, len(fields) - 1) for record in listed.split(_RECORD) if record.strip()]


def _hotfixes_on(checkout: Path, branch: str, head: str, *, run: Run) -> list[_Hotfix]:
    hotfixes = []
    for commit, subject, made, message in _commits(checkout, f"refs/remotes/origin/{branch}..{head}",
                                                   "%H", "%s", "%ct", "%B", run=run):
        if not (originals := frozenset(_STANDS_FOR.findall(message))):
            return []
        hotfixes.append(_Hotfix(commit, subject, int(made), originals))
    return hotfixes


def _has_shipped(hotfix: _Hotfix, checkout: Path, workspace: Path, head: str, target: str, *, run: Run) -> bool:
    by_repo: dict[str, set[tuple[str, str]]] = {}
    for email, seconds, repo in hotfix.originals:
        by_repo.setdefault(repo, set()).add((email, seconds))
    return all(originals & _shipped_in(repo, hotfix, checkout=checkout, workspace=workspace, head=head,
                                        target=target, run=run)
               for repo, originals in by_repo.items())


def _shipped_in(repo: str, hotfix: _Hotfix, *, checkout: Path, workspace: Path, head: str, target: str,
                run: Run) -> set[tuple[str, str]]:
    if not repo:
        return _authors_in_effect(checkout, head, target, run=run)
    released = _pin_of(repo, checkout, target, run=run)
    if released is None:
        return set()
    return _authors_in_effect(Path(workspace) / repo, _pin_of(repo, checkout, hotfix.commit, run=run) or released,
                              released, run=run)


def _pin_of(repo: str, checkout: Path, commit: str, *, run: Run) -> str | None:
    return next((pin.tag for pin in sibling_pins_in(_pyproject_at(checkout, commit, run=run)) if pin.repo == repo),
                None)


def _kept_at_its_hotfix(head: str, target: str, unshipped: list[_Hotfix], *, now: Callable[[], float]) -> _Plan:
    newest, oldest = unshipped[0].subject, min(hotfix.made for hotfix in unshipped)
    if now() - oldest >= HOTFIX_SHIPS_WITHIN_S:
        return _Plan(head, target, False, [], f'failed: kept at its hotfix "{newest}" for a day, and that fix has '
                                              f'not shipped the usual way', failed=True)
    return _Plan(head, target, False, [], f'kept at its hotfix "{newest}" until that fix ships the usual way')


def _authors_in_effect(repository: Path, base: str, tip: str, *, run: Run) -> set[tuple[str, str]]:
    since = git_or_none(repository, "merge-base", base, tip, run=run)
    commits = _commits(repository, f"{since}..{tip}" if since else tip, "%H", "%ae", "%at", "%B", run=run)
    undone_by = {undone: commit for commit, _email, _seconds, message in commits
                 for undone in _REVERTS.findall(message)}

    def in_effect(commit: str) -> bool:
        undoing = undone_by.get(commit)
        return undoing is None or not in_effect(undoing)

    return {(email, seconds) for commit, email, seconds, _message in commits if in_effect(commit)}


def _libraries_off(checkout: Path, commit: str, *, run: Run) -> list[SiblingPin]:
    venv = checkout / ".venv"
    if not venv.is_dir():
        return []
    return libraries_off_their_pins(_pyproject_at(checkout, commit, run=run), installed_versions(venv))


def _pyproject_at(checkout: Path, commit: str, *, run: Run) -> str:
    return git_or_none(checkout, "show", f"{commit}:pyproject.toml", run=run) or ""


def _cloning_from_here(workspace: Path, pins: Iterable[SiblingPin], *, run: Run) -> dict[str, str]:
    held = [pin for pin in pins if git_or_none(
        Path(workspace) / pin.repo, "rev-parse", "--verify", "--quiet", f"{pin.tag}^{{commit}}", run=run)]
    settings = {"GIT_CONFIG_COUNT": str(len(held))}
    for index, pin in enumerate(held):
        settings[f"GIT_CONFIG_KEY_{index}"] = f"url.{(Path(workspace) / pin.repo).as_posix()}.insteadOf"
        settings[f"GIT_CONFIG_VALUE_{index}"] = pin.url
    return settings


def is_ancestor(checkout: Path, older: str, newer: str, *, run: Run) -> bool:
    try:
        git(checkout, "merge-base", "--is-ancestor", older, newer, run=run)
    except StepFailed:
        return False
    return True


def _describe(checkout: Path, branch: str, target: str, *, run: Run) -> str:
    tracking = git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", run=run)
    return f"origin/{branch}" if tracking == target else target[:8]


def _carry_out(checkout: Path, plan: _Plan, *, workspace: Path, run: Run) -> str:
    python = str(checkout / ".venv" / "Scripts" / "python.exe")
    changed = git(checkout, "diff", "--name-only", plan.head, plan.target, run=run).splitlines() if plan.moves else []
    pinned = sibling_pins_in(_pyproject_at(checkout, plan.target if plan.moves else plan.head, run=run))
    local = _cloning_from_here(workspace, pinned, run=run)
    steps = []
    if plan.libraries:
        steps.append(("installing its libraries", LIBRARY_S * len(plan.libraries), lambda: run(
            [python, "-m", "pip", "install", *(pin.spec for pin in plan.libraries)], cwd=checkout,
            timeout=PIP_TIMEOUT_S, env=local)))
    if plan.moves:
        steps.append(("moving its code", MOVE_S, lambda: _move(checkout, plan, run=run)))
    if (checkout / ".venv").is_dir() and (plan.libraries or "pyproject.toml" in changed):
        steps.append(("installing it", REINSTALL_S, lambda: run(
            [python, "-m", "pip", "install", "-e", str(checkout), "--config-settings", "editable_mode=compat"],
            cwd=checkout, timeout=PIP_TIMEOUT_S, env=local)))
    with _saying_how_far(checkout, tuple((name, seconds) for name, seconds, _ in steps)) as entering:
        for index, (_name, _seconds, take) in enumerate(steps):
            entering(index)
            take()
    done = [f"moved from {plan.head[:8]} to {plan.target[:8]}"] if plan.moves else []
    if plan.libraries:
        done.append("installed " + ", ".join(f"{pin.package} {pin.tag}" for pin in plan.libraries))
    return "; ".join(done)


def _move(checkout: Path, plan: _Plan, *, run: Run) -> None:
    if is_ancestor(checkout, plan.head, plan.target, run=run):
        git(checkout, "merge", "--ff-only", "--quiet", plan.target, run=run)
    else:
        git(checkout, "reset", "--keep", "--quiet", plan.target, run=run)


@contextlib.contextmanager
def _saying_how_far(checkout: Path, steps: tuple[tuple[str, float], ...]):
    path = checkout / ".git" / PROGRESS
    pid = os.getpid()

    def entering(step: int) -> None:
        publish_whole(path, json.dumps({"steps": steps, "step": step, "since": time.time(), "pid": pid,
                                        "started": _started(pid)}))

    try:
        yield entering
    finally:
        path.unlink(missing_ok=True)


def progress_of(checkout: Path) -> UpdateProgress | None:
    """How far the update of *checkout* under way has got, or None when none is."""
    try:
        document = json.loads((Path(checkout) / ".git" / PROGRESS).read_text(encoding="utf-8"))
        progress = UpdateProgress(
            steps=tuple((str(name), float(seconds)) for name, seconds in document["steps"]),
            step=int(document["step"]), since=float(document["since"]), pid=int(document["pid"]),
            started=document["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return progress if _started(progress.pid) == progress.started else None


def _started(pid: int) -> int | None:
    return win32.process_started(pid) if os.name == "nt" else None


def bring_up(checkout: Path, *, workspace: Path, run: Run = run, wait_s: float = SCHEDULED_WAIT_S,
             in_use: InUse = running_from, previous: Outcome | None = None,
             now: Callable[[], float] = time.time) -> Outcome:
    checkout, target = Path(checkout), None
    try:
        branch, target = _branch_and_target(checkout, run=run)
        if (previous is not None and previous.failed and previous.target == target
                and now() - previous.at < RETRY_FAILED_AFTER_S and not _libraries_off(checkout, "HEAD", run=run)):
            return previous
        said = _bring_up_to(checkout, branch, target, workspace=workspace, run=run, wait_s=wait_s, in_use=in_use,
                            now=now)
        return Outcome(said, now(), False, target)
    except _LeftAlone as left:
        return Outcome(_not_waiting(checkout, str(left)), now(), left.failed, target)
    except Busy as busy:
        return Outcome(f"busy: {busy}", now(), False, target)
    except StepFailed as failed:
        return Outcome(f"failed: {failed}", now(), True, target)


def heading_for(checkout: Path, *, run: Run = run) -> str:
    try:
        branch, target = _branch_and_target(checkout, run=run)
    except _LeftAlone as left:
        raise StepFailed(f"{Path(checkout).name} {left}") from None
    plan = _plan(checkout, branch, target, workspace=Path(checkout).parent, run=run, now=time.time)
    return plan.target if plan.moves else plan.head


def _bring_up_to(checkout: Path, branch: str, target: str, *, workspace: Path, run: Run, wait_s: float,
                 in_use: InUse, now: Callable[[], float]) -> str:
    plan = _plan(checkout, branch, target, workspace=workspace, run=run, now=now)
    if plan.settled:
        return _settle(checkout, plan)
    with the_turn(checkout, wait_s=wait_s):
        plan = _plan(checkout, branch, target, workspace=workspace, run=run, now=now)
        if plan.settled:
            return _settle(checkout, plan)
        if running := in_use(_venvs_watched(checkout, workspace)):
            return _waiting_for(checkout, running)
        return _not_waiting(checkout, _carry_out(checkout, plan, workspace=workspace, run=run))


def _settle(checkout: Path, plan: _Plan) -> str:
    if plan.failed:
        raise _LeftAlone(plan.settled, failed=True)
    return _not_waiting(checkout, plan.settled)


def _waiting_for(checkout: Path, running: list[processes.Process]) -> str:
    said = f"waiting for {', '.join(sorted({process.name for process in running}))} to close"
    (checkout / ".git" / WAITING).write_text(said + "\n", encoding="utf-8")
    return said


def _not_waiting(checkout: Path, said: str) -> str:
    (checkout / ".git" / WAITING).unlink(missing_ok=True)
    return said


# --- A pass, and a launch ---------------------------------------------------------


def _status(state: Path) -> dict:
    try:
        document = json_store.read_json(state / STATUS_NAME)
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _previous(status: Mapping) -> dict[str, Outcome]:
    recorded = status.get("checkouts", {})
    return {name: Outcome(**entry) for name, entry in recorded.items()
            if isinstance(entry, dict) and set(entry) == {field.name for field in dataclasses.fields(Outcome)}}


def _record(state: Path, outcomes: Mapping[str, Outcome], previous: Mapping[str, Outcome], *,
            finished: float | None = None, github: str | None = None) -> None:
    for name, outcome in outcomes.items():
        if outcome.said != getattr(previous.get(name), "said", None):
            (_log.warning if outcome.failed else _log.info)("%s: %s", name, outcome.said)

    def update(document: dict) -> dict:
        document.setdefault("checkouts", {}).update(
            {name: dataclasses.asdict(outcome) for name, outcome in outcomes.items()})
        if finished is not None:
            document["pass_finished"] = finished
        if github is not None:
            document["github"] = github
        return document

    json_store.locked_update(state / STATUS_NAME, update)


def _on_github(checkout: Path, *, run: Run) -> tuple[str, str] | None:
    match = _ON_GITHUB.search(git_or_none(checkout, "config", "--get", "remote.origin.url", run=run) or "")
    return (match["owner"].casefold(), match["name"].casefold()) if match else None


def _heads_on_github(checkouts: Iterable[Path], *, run: Run) -> dict[Path, tuple[str, str]]:
    places = {checkout: _on_github(checkout, run=run) for checkout in checkouts}
    heads = {}
    for owner in sorted({place[0] for place in places.values() if place}):
        answer = json.loads(run(["gh", "api", "graphql", "-f", f"query={_HEADS_QUERY}", "-f", f"owner={owner}"],
                                timeout=GIT_TIMEOUT_S))
        for node in answer["data"]["repositoryOwner"]["repositories"]["nodes"]:
            if branch := node.get("defaultBranchRef"):
                heads[(owner, node["name"].casefold())] = (branch["name"], branch["target"]["oid"])
    return {checkout: heads[place] for checkout, place in places.items() if place in heads}


def _worth_fetching(checkout: Path, branch: str, head: tuple[str, str] | None, *, run: Run,
                    now: Callable[[], float]) -> bool:
    if head is not None and head[0] == branch:
        tracking = git_or_none(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", run=run)
        return tracking != head[1]
    try:
        fetched = (checkout / ".git" / "FETCH_HEAD").stat().st_mtime
    except OSError:
        return True
    return now() - fetched >= FETCH_UNASKED_AFTER_S


def _ask_github(checkouts: list[Path], *, run: Run) -> tuple[dict[Path, tuple[str, str]], str]:
    try:
        return _heads_on_github(checkouts, run=run), GITHUB_ANSWERS
    except StepFailed as unreachable:
        why = str(unreachable)
    except (ValueError, KeyError, TypeError) as unreadable:
        why = f"its answer could not be read ({unreadable!r})"
    return {}, (f"could not be asked what has shipped, so each checkout is fetched every "
                f"{FETCH_UNASKED_AFTER_S / 60:g} minutes instead: {why}")


def keep_the_claude_app_off(checkout: Path) -> None:
    attributes = Path(checkout) / ".git" / "info" / "attributes"
    held = (attributes.read_text(encoding="utf-8") if attributes.is_file() else "").splitlines()
    if HANDS_OFF_RULE not in held:
        attributes.parent.mkdir(exist_ok=True)
        attributes.write_text("\n".join([*held, HANDS_OFF_RULE]) + "\n", encoding="utf-8", newline="\n")


def keep_up(workspace: Path, state: Path, *, fetch: bool = True, run: Run = run,
            wait_s: float = SCHEDULED_WAIT_S, in_use: InUse = running_from,
            now: Callable[[], float] = time.time) -> dict[str, Outcome]:
    status = _status(state)
    previous = _previous(status)
    outcomes = {}
    checkouts = checkouts_in(workspace)
    heads, github = _ask_github(checkouts, run=run) if fetch else ({}, None)
    if github is not None and github != status.get("github", GITHUB_ANSWERS):
        (_log.info if github == GITHUB_ANSWERS else _log.warning)("GitHub: %s", github)
    for checkout in checkouts:
        try:
            keep_the_claude_app_off(checkout)
        except OSError as stuck:
            _log.warning("%s: could not keep the Claude app off: %s", checkout.name, stuck)
        branch = default_branch(checkout, run=run)
        if fetch and branch and _worth_fetching(checkout, branch, heads.get(checkout), run=run, now=now):
            try:
                git(checkout, "fetch", "--quiet", "origin", branch, run=run)
            except StepFailed as unreachable:
                _log.warning("%s: could not fetch: %s", checkout.name, unreachable)
        outcomes[checkout.name] = bring_up(checkout, workspace=workspace, run=run, wait_s=wait_s,
                                           in_use=in_use, previous=previous.get(checkout.name), now=now)
    _record(state, outcomes, previous, finished=now(), github=github)
    return outcomes


def before_launch(checkout: Path, workspace: Path, state: Path, *, run: Run = run,
                  wait_s: float = LAUNCH_WAIT_S, in_use: InUse = running_from,
                  now: Callable[[], float] = time.time) -> dict[str, Outcome]:
    previous = _previous(_status(state))
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
    try:
        if options.before_launch:
            checkout = options.before_launch.resolve()
            before_launch(checkout, options.workspace or checkout.parent, state, run=run, in_use=in_use)
        else:
            with contextlib.suppress(Busy), _holding_alone(state / ONE_PASS, wait_s=0):
                keep_up(options.workspace or workspace_of(here), state, run=run, in_use=in_use)
    except Exception:
        _log.exception("the %s ended on an error", "update before a launch" if options.before_launch else "pass")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
