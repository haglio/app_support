from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from app_support.coupling import measured_sections
from app_support.gates import BASELINE_PATH, Checkout, over
from app_support.private_reach import private_imports, reaches_in

_COMMAND = "python -m app_support.gates.baseline"
STATED_RENAMES_PATH = "tools/quality_baseline_renames.json"
_NAMES_AN_EXTERNALITY = re.compile(
    r"\b(Qt|PyQt\d?|PySide\d?|shiboken\d?|Q[A-Z][a-z]\w+|mpv|libmpv|Win32|Windows|ctypes|pywin32|pCloud|ComfyUI|pygame|OpenXR|ffmpeg|ffprobe|FFmpeg"
    r"|CPython|pytest|pip|git|GitHub|Chrome|SQLite|sqlite3|Pillow|PIL|vosk|Whisper|Ollama|ruff|vulture|VBScript|PowerShell|GGUF|safetensors|kohya|lycoris|WAN|SDXL|SD1.5|Flux|LTX|Krea|Topaz|COM|HRESULT|PE|psutil|wscript|TOML|Task Scheduler|Claude app|OSR2)\b")
_MARKER_FOR_A_TOOL = re.compile(r"#\s*(noqa|type:|pragma:|pylint:|ruff:|fmt:|nosec|isort:|mypy:|pyright:)")


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


def _is_on_a_line_of_code(token: tokenize.TokenInfo) -> bool:
    return bool(token.line[:token.start[1]].strip())


def _comments(source: str) -> Iterator[tokenize.TokenInfo]:
    return (token for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT)


def _comment_blocks(source: str) -> Iterator[list[int]]:
    block: list[int] = []
    for token in _comments(source):
        if _is_on_a_line_of_code(token):
            continue
        if block and token.start[0] != block[-1] + 1:
            yield block
            block = []
        block.append(token.start[0])
    if block:
        yield block


def _docstring_blocks(source: str) -> Iterator[list[int]]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            yield list(range(node.lineno, node.end_lineno + 1))


def _trailing(source: str) -> list[str]:
    return [token.string for token in _comments(source)
            if _is_on_a_line_of_code(token) and not _MARKER_FOR_A_TOOL.match(token.string)]


def trailing_comments(source: str) -> int:
    try:
        return sum(not _NAMES_AN_EXTERNALITY.search(comment) for comment in _trailing(source))
    except (tokenize.TokenError, IndentationError):
        return 0


def _named_whole_lines(source: str) -> list[int]:
    lines = source.splitlines()
    try:
        blocks = [*_comment_blocks(source), *_docstring_blocks(source)]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return [row for block in blocks if _NAMES_AN_EXTERNALITY.search("\n".join(lines[row - 1] for row in block))
            for row in block if lines[row - 1].strip()]


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


def _measured_over_code_and_tests(checkout: Checkout, measure: Callable[[str], int]) -> dict[str, int]:
    counted = {_key(path, checkout): measure(_text(path))
               for path in _python_under((*checkout.code, *checkout.own_tests))}
    return {key: lines for key, lines in counted.items() if lines}


def _prose_naming_nothing_outside(source: str) -> int:
    return prose_lines(source) - len(_named_whole_lines(source))


def _prose(checkout: Checkout) -> dict[str, int]:
    return _measured_over_code_and_tests(checkout, _prose_naming_nothing_outside)


def _trailing_counts(checkout: Checkout) -> dict[str, int]:
    return _measured_over_code_and_tests(checkout, trailing_comments)


def _reach_listing(checkout: Checkout) -> dict[str, list[str]]:
    listing = {}
    for path in _python_under(checkout.code):
        key = _key(path, checkout)
        reaches = reaches_in(_text(path))
        if reaches:
            listing[key] = [f"{key}:{reach.line}: {reach.written}" for reach in reaches]
    return listing


def _reaches(checkout: Checkout) -> dict[str, int]:
    return {key: len(found) for key, found in _reach_listing(checkout).items()}


def _import_listing(checkout: Checkout) -> dict[str, list[str]]:
    return private_imports(_python_under(checkout.code), checkout.root)


def _imports(checkout: Checkout) -> dict[str, int]:
    return {key: len(found) for key, found in _import_listing(checkout).items()}


def _counted(section: str) -> Callable[[Checkout], dict[str, int]]:
    return lambda checkout: measured_sections(checkout)[section]


class Count(NamedTuple):
    section: str
    measure: Callable[[Checkout], dict[str, int]]
    remedy: str
    listing: Callable[[Checkout], dict[str, list[str]]] | None = None


COUNTS = (
    Count("prose_lines", _prose, "say it in a name or a test, or delete it"),
    Count("trailing_comments", _trailing_counts, "say it in a name or a test, or delete it"),
    Count("private_reaches", _reaches, "ask the object for what you need rather than reading its private name",
          _reach_listing),
    Count("private_imports", _imports, "make the name public, or stop reading it from outside", _import_listing),
    Count("mutables_imported", _counted("mutables_imported"), "pass it, or freeze it, rather than sharing it from a module"),
    Count("library_patches", _counted("library_patches"), "use what the library's testing module offers, or add it there"),
)


def count_named(section: str) -> Count:
    return next(count for count in COUNTS if count.section == section)


def _read_by_a_count(sections: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {count.section: sections[count.section] for count in COUNTS if count.section in sections}


def owed(entries: dict[str, int], live: dict[str, int]) -> dict[str, tuple[int, int]]:
    return {key: (live.get(key, 0), entry) for key, entry in entries.items() if live.get(key, 0) < entry}


def lowered(entries: dict[str, int], live: dict[str, int]) -> dict[str, int]:
    kept = {key: min(entry, live.get(key, 0)) for key, entry in entries.items()}
    return {key: entry for key, entry in kept.items() if entry}


def carried(entries: dict[str, int], renames: dict[str, str]) -> dict[str, int]:
    moved = {renames[key]: entry for key, entry in entries.items() if key in renames}
    return {**{key: entry for key, entry in entries.items() if key not in renames}, **moved}


def _write_sections(root: Path, sections: dict[str, dict[str, int]]) -> None:
    path = root / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sections, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def assert_count_holds(checkout: Checkout, count: Count) -> None:
    assert checkout.sections is not None, f"{checkout.root} has no {BASELINE_PATH}: run {_COMMAND}"
    entries = checkout.sections.get(count.section)
    if entries is None:
        return
    live = count.measure(checkout)
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


def _renames(root: Path) -> dict[str, str]:
    stated = root / STATED_RENAMES_PATH
    return {**renamed_since_main(root), **(json.loads(_text(stated)) if stated.is_file() else {})}


def _sections_at_main(root: Path) -> dict[str, dict[str, int]] | None:
    left = _where_this_left_main(root)
    held = _git(root, "show", f"{left}:{BASELINE_PATH}") if left else None
    return json.loads(held) if held else None


def assert_nothing_stands_above_main(checkout: Checkout) -> None:
    held_at_main = _sections_at_main(checkout.root)
    if held_at_main is None:
        return
    here, at_main = _read_by_a_count(checkout.sections or {}), _read_by_a_count(held_at_main)
    renames = _renames(checkout.root)
    told = [f"{section} {key} stands at {held}, above the {entry} main holds"
            for section, entries in here.items() if section in at_main
            for key, (held, entry) in over(carried(at_main[section], renames), entries).items()]
    told += [f"{section} is gone from the file, and main holds it" for section in at_main if section not in here]
    assert not told, "\n".join([*told, "An entry only comes down: bring the number down rather than the bar up."])


def _settled_section(checkout: Checkout, section: str, entries: dict[str, int], live: dict[str, int], said) -> dict[str, int]:
    refused = over(entries, live)
    for key, (held, entry) in sorted(refused.items()):
        said(f"refused {section} {key}: it holds {held}, over its entry of {entry}")
    for key, (held, entry) in sorted(owed(entries, live).items()):
        if (checkout.root / key).exists():
            said(f"lowered {section} {key} from {entry} to {held}")
        else:
            said(f"could not match {section} {key}: nothing is there now and git names no rename of it")
    return lowered(entries, live)


def main_in(checkout: Checkout, *, said: Callable[[str], None] = print) -> int:
    on_file = _read_by_a_count(checkout.sections or {})
    renames = _renames(checkout.root)
    sections = {}
    refusals = 0
    for count in COUNTS:
        section, live = count.section, count.measure(checkout)
        if section not in on_file:
            sections[section] = live
            continue
        entries = carried(on_file[section], renames)
        for key in sorted(set(on_file[section]) - set(entries)):
            said(f"carried {section} {key} to {renames[key]}")
        refusals += len(over(entries, live))
        sections[section] = _settled_section(checkout, section, entries, live, said)
    _write_sections(checkout.root, sections)
    return 1 if refusals else 0


if __name__ == "__main__":
    sys.exit(main_in(Checkout(Path.cwd())))
