"""Run the tests a branch added or changed many times, and refuse any that fail once."""
from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any, NamedTuple

from app_support.changed_tests import changed_test_ids
from app_support.subprocess_utils import hidden_subprocess_kwargs

__all__ = ["Repeats", "assert_they_hold_up", "busy_machine", "main"]


@contextmanager
def busy_machine(*, workers: int, give_way: bool = True) -> Iterator[list[subprocess.Popen]]:
    started_as = _giving_way() if give_way else hidden_subprocess_kwargs()
    interpreter = getattr(sys, "_base_executable", sys.executable)
    spinning = [subprocess.Popen([interpreter, "-c", "while True: pass"], **started_as)
                for _ in range(workers)]
    try:
        yield spinning
    finally:
        for worker in spinning:
            worker.kill()
            worker.wait()


class Repeats(NamedTuple):
    """The tests the gate put through all of its runs, and the ones it left out."""

    repeated: list[str]
    skipped: list[str]


def assert_they_hold_up(root: Path, ids: list[str], *, runs: int, python: str = sys.executable,
                        load: Callable[[], AbstractContextManager] | None = None,
                        budget: float | None = None) -> Repeats:
    """Repeat *ids* *runs* times each, within *budget* seconds if one is given.

    Without a cap, a branch that renames a module can schedule thousands of runs
    and take the job past its own ceiling, which reports nothing at all and turns
    a green branch away.  So the tests are taken in chunks, each chunk repeated to
    the end before the next is started, no run is begun that the measured pace
    says would end past the cap, and what there is no room for comes back named
    rather than dropped."""
    if not ids:
        return Repeats([], [])
    command = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    deadline = None if budget is None else monotonic() + budget
    pace = _Pace()
    repeated: list[str] = []
    left = list(ids)
    with (load or _every_core_busy)():
        while left:
            chunk = _the_next_chunk(command, left, runs=runs, deadline=deadline, pace=pace)
            if not chunk:
                break
            for run in range(1, runs + 1):
                if deadline is not None and monotonic() + pace.seconds_for(chunk) > deadline:
                    return Repeats(repeated, left)
                started = monotonic()
                _one_run(command, chunk, root, run=run, runs=runs)
                pace.measured(monotonic() - started, len(chunk))
            repeated += chunk
            left = left[len(chunk):]
    return Repeats(repeated, left)


def _one_run(command: list[str], chunk: list[str], root: Path, *, run: int, runs: int) -> None:
    done = subprocess.run([*command, *chunk], cwd=root, capture_output=True, text=True,
                          **hidden_subprocess_kwargs())
    if done.returncode != 0:
        raise AssertionError(
            f"a new or changed test failed on run {run} of {runs}; a test that fails "
            f"even once is flaky and cannot land:\n{done.stdout}{done.stderr}")


_LONGEST_COMMAND_LINE = 32_766  # CreateProcessW's limit, less its terminating null


class _Pace:
    """What one run of one test has been costing, measured as the gate goes."""

    # Tests enough to pace the rest by, few enough to lose to a cap too small for
    # them: what the first chunk holds, there being nothing yet to measure on.
    _TO_MEASURE_ON = 20

    def __init__(self) -> None:
        self.spent = 0.0
        self.test_runs = 0

    def measured(self, seconds: float, test_runs: int) -> None:
        self.spent += seconds
        self.test_runs += test_runs

    def tests_that_fit(self, seconds: float, runs: int) -> int:
        if not self.spent:
            return self._TO_MEASURE_ON
        return max(0, int(seconds * self.test_runs / (self.spent * runs)))

    def seconds_for(self, chunk: list[str]) -> float:
        """What one more run of *chunk* looks like costing -- nothing at all until
        a run has been timed, there being no ground yet to refuse one on."""
        return 0.0 if not self.spent else self.spent * len(chunk) / self.test_runs


def _the_next_chunk(command: list[str], left: list[str], *, runs: int,
                    deadline: float | None, pace: _Pace) -> list[str]:
    holds = _how_many_one_command_line_holds(command, left)
    if deadline is None:
        return left[:holds]
    return left[:min(holds, pace.tests_that_fit(deadline - monotonic(), runs))]


def _how_many_one_command_line_holds(command: list[str], ids: list[str]) -> int:
    room = _LONGEST_COMMAND_LINE - len(subprocess.list2cmdline(command))
    used = 0
    for held, test in enumerate(ids):
        used += 1 + len(subprocess.list2cmdline([test]))
        if held and used > room:
            return held
    return len(ids)


def _every_core_busy(give_way: bool = True) -> AbstractContextManager:
    return busy_machine(workers=os.cpu_count() or 1, give_way=give_way)


def _giving_way() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    return hidden_subprocess_kwargs(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app_support.flake_gate")
    parser.add_argument("--base", required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--only", action="append", default=[], metavar="DIR")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dedicated-machine", action="store_true")
    parser.add_argument("--budget-minutes", type=float, default=None, metavar="MINUTES")
    args = parser.parse_args(argv)
    root = Path.cwd()
    changed = changed_test_ids(root, args.base)
    if args.only:
        ids = [test for test in changed if any(_is_under(test, tree) for tree in args.only)]
    else:
        settings = _pytest_settings(root)
        ids = [test for test in changed if _the_suite_reaches(test, settings)]
    if not ids:
        print(f"no test was added or changed since {args.base}", file=sys.stderr)
        return 0
    print("\n".join(ids))
    try:
        held = assert_they_hold_up(
            root, ids, runs=args.runs, python=args.python,
            load=partial(_every_core_busy, give_way=not args.dedicated_machine),
            budget=None if args.budget_minutes is None else args.budget_minutes * 60)
    except AssertionError as refusal:
        print(refusal, file=sys.stderr)
        return 1
    print(_what_it_got_through(held, runs=args.runs, cap=args.budget_minutes), file=sys.stderr)
    return 0


def _what_it_got_through(held: Repeats, *, runs: int, cap: float | None) -> str:
    """A repeat the cap left out is named, never silently not run."""
    total = len(held.repeated) + len(held.skipped)
    said = [f"repeated {len(held.repeated)} of {total} tests, {runs} times each"]
    if held.skipped:
        said.append(f"the {cap:g} minute cap left {len(held.skipped)} unrepeated:")
        said += held.skipped
    return "\n".join(said)


def _pytest_settings(root: Path) -> dict[str, Any]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    settings = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return settings.get("tool", {}).get("pytest", {}).get("ini_options", {})


def _the_suite_reaches(test: str, settings: dict[str, Any]) -> bool:
    test_paths = settings.get("testpaths", [])
    if test_paths and not any(_is_under(test, tree) for tree in test_paths):
        return False
    directories = test.partition("::")[0].split("/")[:-1]
    return not any(fnmatch.fnmatch(part, pattern)
                   for part in directories for pattern in settings.get("norecursedirs", []))


def _is_under(test: str, tree: str) -> bool:
    return test.startswith(tree.rstrip("/") + "/")


if __name__ == "__main__":
    sys.exit(main())
