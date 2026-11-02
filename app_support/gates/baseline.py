"""The numbers a repo keeps per file, checked in, which only ever move the right way.

    python -m app_support.gates.baseline

lowers what fell, carries what git says was renamed, enters a section the file does not
have yet, and refuses to raise anything. With ``--hold-uncovered`` it only holds the
measurements a suite run in parts has gathered into ``.coverage`` to their entries.
"""
from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

import coverage

from app_support.coverage_gate import UNCOVERED, uncovered_in_report, uncovered_rises
from app_support.gates import BASELINE_PATH, Checkout, over
from app_support.private_reach import private_imports, reaches_in

_COMMAND = "python -m app_support.gates.baseline"
_CLASS_MARK = "::"


def prose_lines(source: str) -> int:
    lines = source.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return 0
    prose: set[int] = set()
    before = tokenize.INDENT
    for token in tokens:
        rows = range(token.start[0], token.end[0] + 1)
        if token.type == tokenize.COMMENT:
            prose.update(row for row in rows if not lines[row - 1].split("#")[0].strip())
        elif token.type == tokenize.STRING and before in (tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL):
            prose.update(row for row in rows if lines[row - 1].strip())
        if token.type not in (tokenize.COMMENT, tokenize.NL):
            before = token.type
    return len(prose)


def _defined_directly(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield statement
        elif not isinstance(statement, ast.ClassDef):
            for field in ("body", "orelse", "finalbody"):
                yield from _defined_directly(getattr(statement, field, []))
            for handler in getattr(statement, "handlers", []):
                yield from _defined_directly(handler.body)


def methods_of(source: str, class_name: str) -> int:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return sum(1 for _ in _defined_directly(node.body))
    return 0


def _python_under(paths: tuple[Path, ...]) -> Iterator[Path]:
    for path in paths:
        if path.is_file():
            yield path
        else:
            yield from sorted(path.rglob("*.py"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _key(path: Path, checkout: Checkout) -> str:
    return path.relative_to(checkout.root).as_posix()


def _prose(checkout: Checkout, _entries: dict[str, int]) -> dict[str, int]:
    counted = {_key(path, checkout): prose_lines(_text(path))
               for path in _python_under((*checkout.code, *checkout.own_tests))}
    return {key: lines for key, lines in counted.items() if lines}


def _reach_listing(checkout: Checkout) -> dict[str, list[str]]:
    listing = {}
    for path in _python_under(checkout.code):
        key = _key(path, checkout)
        reaches = reaches_in(_text(path))
        if reaches:
            listing[key] = [f"{key}:{reach.line}: {reach.written}" for reach in reaches]
    return listing


def _reaches(checkout: Checkout, _entries: dict[str, int]) -> dict[str, int]:
    return {key: len(found) for key, found in _reach_listing(checkout).items()}


def _import_listing(checkout: Checkout) -> dict[str, list[str]]:
    return private_imports(_python_under(checkout.code), checkout.root)


def _imports(checkout: Checkout, _entries: dict[str, int]) -> dict[str, int]:
    return {key: len(found) for key, found in _import_listing(checkout).items()}


def _methods(checkout: Checkout, entries: dict[str, int]) -> dict[str, int]:
    measured = {}
    for key in entries:
        file, class_name = key.split(_CLASS_MARK)
        path = checkout.root / file
        methods = methods_of(_text(path), class_name) if path.is_file() else 0
        if methods:
            measured[key] = methods
    return measured


class Count(NamedTuple):
    section: str
    measure: Callable[[Checkout, dict[str, int]], dict[str, int]]
    remedy: str
    listing: Callable[[Checkout], dict[str, list[str]]] | None = None


COUNTS = (
    Count("prose_lines", _prose, "say it in a name or a test, or delete it"),
    Count("private_reaches", _reaches, "ask the object for what you need rather than reading its private name",
          _reach_listing),
    Count("private_imports", _imports, "make the name public, or stop reading it from outside", _import_listing),
    Count("methods", _methods, "give the new method to a collaborator, or to a new one"),
)


def count_named(section: str) -> Count:
    return next(count for count in COUNTS if count.section == section)


def owed(entries: dict[str, int], live: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {key: (live.get(key, 0), entry) for key, entry in entries.items() if live.get(key, 0) < entry}


def lowered(entries: dict[str, int], live: dict[str, int]) -> dict[str, int]:
    kept = {key: min(entry, live.get(key, 0)) for key, entry in entries.items()}
    return {key: entry for key, entry in kept.items() if entry}


def _renamed_key(key: str, renames: dict[str, str]) -> str:
    file, mark, class_name = key.partition(_CLASS_MARK)
    return f"{renames.get(file, file)}{mark}{class_name}"


def carried(entries: dict[str, int], renames: dict[str, str]) -> dict[str, int]:
    moved = {_renamed_key(key, renames): entry for key, entry in entries.items() if _renamed_key(key, renames) != key}
    return {**{key: entry for key, entry in entries.items() if _renamed_key(key, renames) == key}, **moved}


def _write_sections(root: Path, sections: dict[str, dict[str, int]]) -> None:
    path = root / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sections, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def assert_count_holds(checkout: Checkout, count: Count) -> None:
    entries = (checkout.sections or {}).get(count.section)
    if entries is None:
        return
    live = count.measure(checkout, entries)
    told = [f"{key} holds {held} {count.section}, over its entry of {entry}: {count.remedy}"
            for key, (held, entry) in over(entries, live).items()]
    told += [f"{key} holds {held} {count.section}, under its entry of {entry}: run {_COMMAND}"
             for key, (held, entry) in owed(entries, live).items()]
    assert not told, "\n".join([*told, *_lines_behind(checkout, count, over(entries, live))])


def _lines_behind(checkout: Checkout, count: Count, rises: dict[str, tuple[int, int]]) -> list[str]:
    listing = count.listing(checkout) if count.listing and rises else {}
    return [line for key in rises for line in listing.get(key, ())]


def _git(root: Path, *args: str) -> str | None:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", check=False)
    return done.stdout if done.returncode == 0 else None


def _where_this_left_main(root: Path) -> str | None:
    left = _git(root, "merge-base", "HEAD", "origin/main")
    return left.strip() if left else None


def renamed_since_main(root: Path) -> dict[str, str]:
    left = _where_this_left_main(root)
    listed = _git(root, "diff", "-M", "--name-status", "--diff-filter=R", left) if left else None
    return {old: new for _, old, new in (line.split("\t") for line in (listed or "").splitlines())}


def _sections_at_main(root: Path) -> dict[str, dict[str, int]] | None:
    left = _where_this_left_main(root)
    held = _git(root, "show", f"{left}:{BASELINE_PATH}") if left else None
    return json.loads(held) if held else None


def assert_nothing_stands_above_main(checkout: Checkout) -> None:
    here, at_main = checkout.sections, _sections_at_main(checkout.root)
    if here is None or at_main is None:
        return
    renames = renamed_since_main(checkout.root)
    told = [f"{section} {key} stands at {held}, above the {entry} main holds"
            for section, entries in here.items() if section in at_main
            for key, (held, entry) in over(carried(at_main[section], renames), entries).items()]
    assert not told, "\n".join([*told, "An entry only comes down: bring the number down rather than the bar up."])


def _last_run(root: Path):
    data_file = root / ".coverage"
    if not data_file.is_file():
        return None
    last = coverage.Coverage(data_file=str(data_file), config_file=str(root / ".coveragerc"))
    last.load()
    return last if last.get_data().measured_files() else None


def _measures(checkout: Checkout, sections: dict[str, dict[str, int]], said) -> Iterator[tuple[str, dict[str, int]]]:
    for count in COUNTS:
        yield count.section, count.measure(checkout, sections.get(count.section, {}))
    last = _last_run(checkout.root)
    if last is not None:
        yield UNCOVERED, uncovered_in_report(last, checkout.root)
    elif UNCOVERED in sections:
        said(f"left {UNCOVERED} as it was: no whole run's .coverage to read")


def _exists(checkout: Checkout, key: str) -> bool:
    return (checkout.root / key.partition(_CLASS_MARK)[0]).exists()


def _settled_section(checkout: Checkout, section: str, entries: dict[str, int], live: dict[str, int], said) -> dict[str, int]:
    refused = over(entries, live)
    for key, (held, entry) in sorted(refused.items()):
        said(f"refused {section} {key}: it holds {held}, over its entry of {entry}")
    for key, (held, entry) in sorted(owed(entries, live).items()):
        if _exists(checkout, key):
            said(f"lowered {section} {key} from {entry} to {held}")
        else:
            said(f"could not match {section} {key}: nothing is there now and git names no rename of it")
    return lowered(entries, live)


def main_in(checkout: Checkout, *, said: Callable[[str], None] = print) -> int:
    on_file = checkout.sections or {}
    renames = renamed_since_main(checkout.root)
    sections = dict(on_file)
    refusals = 0
    for section, live in _measures(checkout, on_file, said):
        if section not in on_file:
            sections[section] = live
            continue
        entries = carried(on_file[section], renames)
        for key in sorted(set(on_file[section]) - set(entries)):
            said(f"carried {section} {key} to {_renamed_key(key, renames)}")
        refusals += len(over(entries, live))
        sections[section] = _settled_section(checkout, section, entries, live, said)
    _write_sections(checkout.root, sections)
    return 1 if refusals else 0


def hold_uncovered(checkout: Checkout, *, said: Callable[[str], None] = print) -> int:
    last = _last_run(checkout.root)
    if last is None:
        said("no whole run's .coverage to read")
        return 1
    rises = uncovered_rises(checkout.root, last)
    for rise in rises:
        said(rise)
    return 1 if rises else 0


if __name__ == "__main__":
    command = hold_uncovered if "--hold-uncovered" in sys.argv else main_in
    sys.exit(command(Checkout(Path.cwd())))
