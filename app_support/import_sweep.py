"""Import every module a checkout's pyproject packages, in the interpreter its app runs on."""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

__all__ = ["EACH_WITHIN_S", "NothingToSweep", "Sweep", "main", "sweep"]

EACH_WITHIN_S = 120.0
_POLL_S = 0.1

_IMPORT_EACH = """\
import importlib, json, sys, traceback
checkout, record = sys.argv[1], sys.argv[2]
sys.path.insert(0, checkout)
with open(record, "a", encoding="utf-8") as sink:
    for name in json.loads(sys.stdin.read()):
        try:
            importlib.import_module(name)
            failure = None
        except BaseException:
            failure = traceback.format_exc()
        sink.write(json.dumps({"module": name, "failure": failure}) + "\\n")
        sink.flush()
"""


class NothingToSweep(Exception):
    pass


@dataclass(frozen=True)
class Sweep:
    imported: list[str]
    failures: dict[str, str]


def sweep(checkout: Path, *, python: str, each_within_s: float = EACH_WITHIN_S,
          env: Mapping[str, str] | None = None) -> Sweep:
    checkout = Path(checkout)
    left = _modules_of(checkout)
    outcomes: dict[str, str | None] = {}
    with tempfile.TemporaryDirectory() as scratch:
        record = Path(scratch) / "imports.jsonl"
        while left:
            why_it_stopped = _import_in_one_interpreter(python, checkout, left, record, each_within_s, env=env)
            outcomes.update((outcome["module"], outcome["failure"]) for outcome in _recorded(record))
            left = [module for module in left if module not in outcomes]
            if left:
                outcomes[left.pop(0)] = why_it_stopped
    return Sweep([module for module, failure in outcomes.items() if failure is None],
                 {module: failure for module, failure in outcomes.items() if failure is not None})


def _import_in_one_interpreter(python: str, checkout: Path, modules: list[str], record: Path,
                               each_within_s: float, *, env: Mapping[str, str] | None) -> str:
    said = record.with_name("stderr.txt")
    with said.open("w", encoding="utf-8") as stderr:
        child = subprocess.Popen([python, "-c", _IMPORT_EACH, str(checkout), str(record)], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=stderr, text=True, cwd=checkout, env=env,
                                 **hidden_subprocess_kwargs())
        child.stdin.write(json.dumps(modules))
        child.stdin.close()
        done, since = _lines_in(record), time.monotonic()
        while child.poll() is None:
            if (now_done := _lines_in(record)) != done:
                done, since = now_done, time.monotonic()
            elif time.monotonic() - since > each_within_s:
                child.kill()
                child.wait()
                return f"it did not finish importing within {each_within_s:g} s"
            time.sleep(_POLL_S)
    return (f"the interpreter ended with exit code {child.returncode} while importing it:\n"
            f"{said.read_text(encoding='utf-8', errors='replace')}")


def _lines_in(record: Path) -> int:
    try:
        return record.read_bytes().count(b"\n")
    except FileNotFoundError:
        return 0


def _recorded(record: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    except FileNotFoundError:
        return []


_NOT_IMPORTED = frozenset({"__init__", "__main__"})


def _modules_of(checkout: Path) -> list[str]:
    return [module for package in _packages_of(checkout) for module in [package, *_modules_in(checkout, package)]]


def _packages_of(checkout: Path) -> list[str]:
    declared = tomllib.loads((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    include = declared.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("include", [])
    packages = [name for name in _packages_under(checkout) if any(fnmatch.fnmatch(name, pattern) for pattern in include)]
    if not packages:
        raise NothingToSweep(f"{checkout}: no package matches the include of [tool.setuptools.packages.find]")
    return packages


def _packages_under(folder: Path, prefix: str = "") -> Iterator[str]:
    for inside in sorted(folder.iterdir()):
        if inside.is_dir() and "." not in inside.name and (inside / "__init__.py").is_file():
            yield f"{prefix}{inside.name}"
            yield from _packages_under(inside, f"{prefix}{inside.name}.")


def _modules_in(checkout: Path, package: str) -> list[str]:
    sources = sorted(checkout.joinpath(*package.split(".")).glob("*.py"))
    return [f"{package}.{source.stem}" for source in sources if source.stem not in _NOT_IMPORTED]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app_support.import_sweep")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("checkout", nargs="?", default=".")
    args = parser.parse_args(argv)
    try:
        swept = sweep(Path(args.checkout).resolve(), python=args.python)
    except NothingToSweep as refusal:
        print(refusal, file=sys.stderr)
        return 1
    for module, failure in swept.failures.items():
        print(f"--- {module}\n{failure}", file=sys.stderr)
    every = len(swept.imported) + len(swept.failures)
    if swept.failures:
        print(f"{len(swept.failures)} of {every} modules did not import", file=sys.stderr)
        return 1
    print(f"imported all {every} modules", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
