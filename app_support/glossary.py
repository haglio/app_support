from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

SCREEN_NOUNS = frozenset((
    "tile", "card", "badge", "chip", "scrim", "plate", "strip", "cell", "slot", "pane",
    "panel", "console", "band", "toast", "banner", "gutter", "shelf", "tray", "drawer",
    "dial", "pill", "ribbon", "dock", "sidebar", "swatch", "plaque", "placard", "sticker",
    "lozenge", "bubble", "veil", "backdrop", "halo", "glow", "sheet", "deck", "hud", "map",
    "bank", "toolbar", "collage", "splash", "notice", "recents", "bookmark",
))

_STATUSES = frozenset({"ruled", "his_word", "agreed", "unruled", "kept"})
_COLUMNS = frozenset({"id", "thing", "screen", "his_word", "code_today", "code_word", "status"})

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_IDENTIFIER_ONLY = re.compile(r"[A-Za-z0-9_]+")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


class SourceLine(NamedTuple):
    where: str
    number: int
    tokens: list[str]
    words: list[str]
    text: str


def _words_of(identifier: str) -> list[str]:
    return [m.group(0) for piece in identifier.split("_") for m in _WORD.finditer(piece)]


def _words_of_phrase(phrase: str) -> list[str]:
    return [w.lower() for token in phrase.split() for w in _words_of(token)]


def source_lines(folders: Iterable[Path]) -> list[SourceLine]:
    lines = []
    for folder in folders:
        for path in sorted(folder.rglob("*.py")):
            where = path.relative_to(folder.parent).as_posix()
            for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                tokens = _IDENTIFIER.findall(text)
                lines.append(SourceLine(where, number, tokens, [w for token in tokens for w in _words_of(token)], text))
    return lines


def _rows(glossary: Path) -> list[dict]:
    return json.loads(glossary.read_text(encoding="utf-8"))["things"]


def assert_rows_are_whole(glossary: Path) -> None:
    rows = _rows(glossary)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "two rows share an id"
    for row in rows:
        missing = _COLUMNS - set(row)
        assert not missing, f"{row.get('id')} lacks {sorted(missing)}"
        assert row["status"] in _STATUSES, f"{row['id']}: unknown status {row['status']!r}"
        assert row["thing"].strip(), f"{row['id']} does not say what it is"
        assert row["code_today"], f"{row['id']} names no word the code says today"
        if row["status"] == "ruled":
            assert row.get("ruled"), f"{row['id']} is ruled but says not when or where"
            assert row["code_word"], f"{row['id']} is ruled but names no code word"


def _said_somewhere(phrase: str, source: list[SourceLine]) -> bool:
    wanted = " " + " ".join(_words_of_phrase(phrase)) + " "
    return any(wanted in " " + " ".join(w.lower() for w in line.words) + " " for line in source)


def assert_code_today_still_said(glossary: Path, source: list[SourceLine]) -> None:
    stale = [f"{row['id']}: {phrase!r}"
             for row in _rows(glossary)
             for phrase in row["code_today"]
             if not _said_somewhere(phrase, source)]
    assert not stale, "the glossary names code words the code no longer says:\n" + "\n".join(stale)


def _kept(token: str, text: str, keep: list[str]) -> bool:
    return any(k.lower() in (token if _IDENTIFIER_ONLY.fullmatch(k) else text).lower() for k in keep)


def _counted(word: str, token: str) -> bool:
    return not word.isupper() or (token.isupper() and "_" in token)


def _forms(word: str) -> set[str]:
    return {word, word + "s", word + "es"}


def _says(wanted: list[str], words: list[str]) -> bool:
    return words[:-1] == wanted[:-1] and words[-1] in _forms(wanted[-1])


def _lines_saying_each_word(source: list[SourceLine]) -> dict[str, list[int]]:
    saying: dict[str, list[int]] = {}
    for at, line in enumerate(source):
        for word in {w.lower() for w in line.words}:
            saying.setdefault(word, []).append(at)
    return saying


def _mentions(retired: str, keep: list[str], source: list[SourceLine], saying: dict[str, list[int]]) -> list[str]:
    wanted = _words_of_phrase(retired)
    could_say_it = sorted({at for form in _forms(wanted[-1]) for at in saying.get(form, ())})
    hits = []
    for line in (source[at] for at in could_say_it):
        said = [(w.lower(), token) for token in line.tokens if not _kept(token, line.text, keep)
                for w in _words_of(token) if _counted(w, token)]
        for at in range(len(said) - len(wanted) + 1):
            run = said[at:at + len(wanted)]
            if _says(wanted, [w for w, _ in run]):
                hits.append(f"{line.where}:{line.number} {' '.join(token for _, token in run)}")
                break
    return hits


def assert_retired_words_gone(glossary: Path, source: list[SourceLine]) -> None:
    left = []
    saying = _lines_saying_each_word(source)
    for row in _rows(glossary):
        for word in row.get("retired", []):
            left += [f"{row['id']} retired {word!r}: {hit}"
                     for hit in _mentions(word, row.get("keep", []), source, saying)]
    assert not left, "retired words still in the code:\n" + "\n".join(left[:40])


def assert_screen_nouns_have_rows(glossary: Path, source: list[SourceLine], *, more_nouns: Iterable[str] = ()) -> None:
    named = {w.lower()
             for row in _rows(glossary)
             for phrase in row["code_today"] + [row["code_word"] or ""] + row.get("retired", [])
             for w in phrase.split()}
    said = {w.lower() for line in source for w in line.words}
    outside = sorted(((SCREEN_NOUNS | set(more_nouns)) & said) - named)
    assert not outside, f"the code says these nouns for things on screen and the glossary has no row for them: {outside}"
