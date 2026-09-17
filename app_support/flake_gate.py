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
from typing import Any

from app_support.changed_tests import changed_test_ids
from app_support.subprocess_utils import hidden_subprocess_kwargs

__all__ = ["assert_they_hold_up", "busy_machine", "main"]


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


def assert_they_hold_up(root: Path, ids: list[str], *, runs: int, python: str = sys.executable,
                        load: Callable[[], AbstractContextManager] | None = None) -> None:
    if not ids:
        return
    command = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    with (load or _every_core_busy)():
        for run in range(1, runs + 1):
            for batch in _batches_one_command_line_holds(command, ids):
                done = subprocess.run([*command, *batch], cwd=root, capture_output=True, text=True,
                                      errors="replace", **hidden_subprocess_kwargs())
                if done.returncode != 0:
                    raise AssertionError(
                        f"a new or changed test failed on run {run} of {runs}; a test that fails "
                        f"even once is flaky and cannot land:\n{done.stdout}{done.stderr}")


_LONGEST_COMMAND_LINE = 32_766  # CreateProcessW's limit, less its terminating null


def _batches_one_command_line_holds(command: list[str], ids: list[str]) -> Iterator[list[str]]:
    room = _LONGEST_COMMAND_LINE - len(subprocess.list2cmdline(command))
    batch: list[str] = []
    used = 0
    for test in ids:
        size = 1 + len(subprocess.list2cmdline([test]))
        if batch and used + size > room:
            yield batch
            batch, used = [], 0
        batch.append(test)
        used += size
    yield batch


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
        assert_they_hold_up(root, ids, runs=args.runs, python=args.python,
                            load=partial(_every_core_busy, give_way=not args.dedicated_machine))
    except AssertionError as refusal:
        print(refusal, file=sys.stderr)
        return 1
    return 0


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
