from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path
from time import monotonic
from typing import Any, NamedTuple

from app_support.changed_tests import changed_test_ids
from app_support.subprocess_utils import hidden_subprocess_kwargs, run_process_tree

__all__ = ["Effort", "Repeats", "assert_they_hold_up", "busy_machine", "main"]


@contextmanager
def busy_machine(*, workers: int) -> Iterator[list[subprocess.Popen]]:
    interpreter = getattr(sys, "_base_executable", sys.executable)
    spinning = [subprocess.Popen([interpreter, "-c", "while True: pass"], **hidden_subprocess_kwargs())
                for _ in range(workers)]
    try:
        yield spinning
    finally:
        for worker in spinning:
            worker.kill()
            worker.wait()


class Repeats(NamedTuple):
    repeated: list[str]
    skipped: list[str]


class Effort(NamedTuple):
    runs: int
    budget: float | None = None


def assert_they_hold_up(root: Path, ids: list[str], effort: Effort, *, python: str = sys.executable,
                        load: Callable[[], AbstractContextManager] = nullcontext) -> Repeats:
    if not ids:
        return Repeats([], [])
    runs, budget = effort
    command = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    deadline = None if budget is None else monotonic() + budget
    pace = _Pace()
    repeated: list[str] = []
    left = list(ids)
    with load():
        while left:
            chunk = _the_next_chunk(command, left, runs=runs, deadline=deadline, pace=pace)
            if not chunk:
                break
            for run in range(1, runs + 1):
                if deadline is not None and monotonic() + pace.seconds_for(chunk) > deadline:
                    return Repeats(repeated, left)
                started = monotonic()
                within = None if deadline is None else deadline - started
                if not _one_run([*command, *chunk], root, f"{run} of {runs}", within=within):
                    return Repeats(repeated, left)
                pace.measured(monotonic() - started, len(chunk))
            repeated += chunk
            left = left[len(chunk):]
    return Repeats(repeated, left)


def _one_run(argv: list[str], root: Path, which: str, *, within: float | None) -> bool:
    try:
        done = run_process_tree(argv, cwd=root, text=True, errors="replace", timeout=within,
                                **hidden_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        return False
    if done.returncode != 0:
        raise AssertionError(
            f"a new or changed test failed on run {which}; a test that fails "
            f"even once is flaky and cannot land:\n{done.stdout}{done.stderr}")
    return True


_LONGEST_COMMAND_LINE = 32_766  # Win32 CreateProcessW's limit, less its terminating null


class _Pace:
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


def _every_core_busy() -> AbstractContextManager:
    return busy_machine(workers=os.cpu_count() or 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app_support.flake_gate")
    parser.add_argument("--base", required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--only", action="append", default=[], metavar="DIR")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dedicated-machine", action="store_true")
    parser.add_argument("--budget-minutes", type=float, default=None, metavar="MINUTES")
    parser.add_argument("--part", type=int, default=1, metavar="K")
    parser.add_argument("--parts", type=int, default=1, metavar="N")
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
    share = ids[args.part - 1::args.parts]
    if args.parts > 1:
        print(f"part {args.part} of {args.parts} repeats {len(share)} of the {len(ids)} tests "
              f"added or changed since {args.base}", file=sys.stderr)
    print("\n".join(share))
    try:
        held = assert_they_hold_up(
            root, share, Effort(args.runs, None if args.budget_minutes is None else args.budget_minutes * 60),
            python=args.python, load=_every_core_busy if args.dedicated_machine else nullcontext)
    except AssertionError as refusal:
        print(refusal, file=sys.stderr)
        return 1
    print(_what_it_got_through(held, runs=args.runs, cap=args.budget_minutes), file=sys.stderr)
    return 0


def _what_it_got_through(held: Repeats, *, runs: int, cap: float | None) -> str:
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
