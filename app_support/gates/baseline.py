"""The numbers a repo keeps per file, checked in, which only ever move the right way.

    python -m app_support.gates.baseline

lowers what fell, carries what git says was renamed, enters a section the file does not
have yet, and refuses to raise anything. With ``--hold-uncovered`` it only holds the
measurements a suite run in parts has gathered into ``.coverage`` to their entries.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterator
from pathlib import Path

import coverage

from app_support.coupling import measure
from app_support.coupling.classes import measure_classes
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


def _prose(checkout: Checkout) -> dict[str, int]:
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


def _import_listing(checkout: Checkout) -> dict[str, list[str]]:
    return private_imports(_python_under(checkout.code), checkout.root)


def _methods(checkout: Checkout, entries: dict[str, int]) -> dict[str, int]:
    measured = {}
    for key in entries:
        file, class_name = key.split(_CLASS_MARK)
        path = checkout.root / file
        surface = measure_classes(_text(path)).get(class_name) if path.is_file() else None
        if surface and surface.methods:
            measured[key] = surface.methods
    return measured


def _counted(listing: dict[str, list[str]]) -> dict[str, int]:
    return {key: len(found) for key, found in listing.items()}


def live_sections(checkout: Checkout, on_file: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    coupling = measure(checkout)
    return {
        "prose_lines": _prose(checkout),
        "private_reaches": _counted(_reach_listing(checkout)),
        "private_imports": _counted(_import_listing(checkout)),
        "methods": _methods(checkout, on_file.get("methods", {})),
        "over_the_limits": dict(coupling.over_the_limits),
        **{section: dict(counts) for section, counts in coupling.per_file.items()},
    }


_LISTINGS = {"private_reaches": _reach_listing, "private_imports": _import_listing}
_REMEDIES = {
    "prose_lines": "say it in a name or a test, or delete it",
    "private_reaches": "ask the object for what you need rather than reading its private name",
    "private_imports": "make the name public, or stop reading it from outside",
}
_CUT_IT_BACK = "cut it back rather than raising the number"


def owed(entries: dict[str, int], live: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {key: (live.get(key, 0), entry) for key, entry in entries.items() if live.get(key, 0) < entry}


def lowered(entries: dict[str, int], live: dict[str, int]) -> dict[str, int]:
    kept = {key: min(entry, live.get(key, 0)) for key, entry in entries.items()}
    return {key: entry for key, entry in kept.items() if entry}


def _renamed_key(key: str, renames: dict[str, str]) -> str:
    file, mark, within = key.partition(_CLASS_MARK)
    return f"{renames.get(file, file)}{mark}{within}"


def carried(entries: dict[str, int], renames: dict[str, str]) -> dict[str, int]:
    moved = {_renamed_key(key, renames): entry for key, entry in entries.items() if _renamed_key(key, renames) != key}
    return {**{key: entry for key, entry in entries.items() if _renamed_key(key, renames) == key}, **moved}


def _write_sections(root: Path, sections: dict[str, dict[str, int]]) -> None:
    path = root / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sections, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def assert_counts_hold(checkout: Checkout) -> None:
    on_file = checkout.sections or {}
    told: list[str] = []
    for section, live in live_sections(checkout, on_file).items():
        if section not in on_file:
            continue
        rises = over(on_file[section], live)
        told += [f"{key} holds {held} {section}, over its entry of {entry}: {_REMEDIES.get(section, _CUT_IT_BACK)}"
                 for key, (held, entry) in rises.items()]
        told += [f"{key} holds {held} {section}, under its entry of {entry}: run {_COMMAND}"
                 for key, (held, entry) in owed(on_file[section], live).items()]
        told += _lines_behind(checkout, section, rises)
    assert not told, chr(10).join(told)


def _lines_behind(checkout: Checkout, section: str, rises: dict[str, tuple[int, int]]) -> list[str]:
    listing = _LISTINGS[section](checkout) if section in _LISTINGS and rises else {}
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
    yield from live_sections(checkout, sections).items()
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
