from __future__ import annotations

import argparse
import bisect
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from app_support.siblings import primary_checkout_of

_MAX_EXCERPT = 160
_MOST_LISTED = 20
_LONGEST_WORD_KEPT_WHOLE = 3
_BLOCKLIST = Path(".sanitize") / "blocklist.txt"
_SEPARATOR = r"[\s\-_.]*"
_NAME_JOINERS = re.compile(r"[\s\-_.]+")
_INFLECTION = r"(?:'?s|es|ed|ing)?"
_SIBILANT_ENDINGS = ("x", "z", "ch", "sh")


def _stem(word: str) -> str:
    lower = word.lower()
    if (len(lower) <= _LONGEST_WORD_KEPT_WHOLE or not lower.endswith("s")
            or lower.endswith(("ss", "us", "is"))):
        return word
    if lower.endswith("es") and lower[:-2].endswith(_SIBILANT_ENDINGS):
        return word[:-2]
    return word[:-1]


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    term: str = field(repr=False)
    excerpt: str


# The lowercase letters re.IGNORECASE matches as one although str.lower() keeps
# them apart (CPython's re._casefix), each group led by the letter the rest fold
# to. And str.lower() turns U+0130 into two characters where re reads one "i".
_SAME_LETTER = str.maketrans({
    other: group[0]
    for group in (
        "iı", "sſ", "µμ", "ͅιι", "ΐΐ",
        "ΰΰ", "βϐ", "εϵ", "θϑ", "κϰ",
        "πϖ", "ρϱ", "ςσ", "φϕ", "вᲀ",
        "дᲁ", "оᲂ", "сᲃ", "тᲄᲅ",
        "ъᲆ", "ѣᲇ", "ᲈꙋ", "ṡẛ", "ﬅﬆ",
    )
    for other in group[1:]
})


def _fold(text: str) -> str:
    return text.replace("İ", "i").lower().translate(_SAME_LETTER)


@dataclass(frozen=True)
class _Matcher:
    term: str
    pattern: re.Pattern[str]
    needles: tuple[str, ...]


@cache
def _matcher(term: str) -> _Matcher:
    stripped = term.strip()
    parts = stripped.split()
    if parts[-1].isalpha():
        parts[-1] = _stem(parts[-1])
    core = _SEPARATOR.join(re.escape(p) for p in parts)
    left = r"(?<!\w)" if stripped[:1].isalnum() or stripped[:1] == "_" else ""
    right = r"(?!\w)" if stripped[-1:].isalnum() or stripped[-1:] == "_" else ""
    return _Matcher(
        stripped,
        re.compile(left + core + _INFLECTION + right, re.IGNORECASE),
        tuple(sorted(map(_fold, parts), key=len, reverse=True)),
    )


def _compile(terms: Iterable[str]) -> list[_Matcher]:
    return [_matcher(t) for t in terms if t.strip()]


def _present(matchers: Sequence[_Matcher], text: str) -> list[_Matcher]:
    folded = _fold(text)
    return [m for m in matchers if all(needle in folded for needle in m.needles)]


def _redact(line: str, matchers: Sequence[_Matcher]) -> str:
    out = line
    for matcher in matchers:
        out = matcher.pattern.sub("***", out)
    return out.strip()[:_MAX_EXCERPT]


def find_violations(
    text: str,
    terms: Iterable[str],
    *,
    path: str = "<text>",
) -> list[Violation]:
    return _violations_in(text, _compile(terms), path)


def _violations_in(text: str, matchers: Sequence[_Matcher], path: str) -> list[Violation]:
    present = _present(matchers, text)
    lines = text.splitlines()
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line) + 1
    out: list[Violation] = []
    for matcher in present:
        for match in matcher.pattern.finditer(text):
            lineno = bisect.bisect_right(starts, match.start())
            excerpt = _redact(lines[lineno - 1], present) if lines else ""
            out.append(Violation(path, lineno, matcher.term, excerpt))
    out.sort(key=lambda v: (v.line, v.term))
    return out


def blocklist_path(repo: Path) -> Path:
    return primary_checkout_of(repo).resolve().parent / _BLOCKLIST


def load_blocklist(path: Path) -> list[str]:
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def _scan_name(path: str, matchers: Sequence[_Matcher]) -> tuple[str, list[Violation]]:
    words = _NAME_JOINERS.sub(" ", path)
    hits = [m for m in _present(matchers, words) if m.pattern.search(words)]
    if not hits:
        return path, []
    shown = _redact(words, hits)
    return shown, [Violation(shown, 0, m.term, "(in the file's name)") for m in hits]


def _scan(
    named_texts: Iterable[tuple[str, str | OSError | None]], terms: Iterable[str],
) -> list[Violation]:
    matchers = _compile(terms)
    out: list[Violation] = []
    for name, text in named_texts:
        shown, in_name = _scan_name(name, matchers)
        out.extend(in_name)
        if isinstance(text, OSError):
            out.append(Violation(shown, 0, "", f"(could not be read: {type(text).__name__})"))
        elif text is not None:
            out.extend(_violations_in(text, matchers, shown))
    return out


def scan_files(
    paths: Iterable[Path],
    terms: Iterable[str],
    *,
    root: Path | None = None,
) -> list[Violation]:
    return _scan(((str(path.relative_to(root)) if root else str(path), _text_of(path))
                  for path in paths), terms)


def _text_of(path: Path) -> str | OSError | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return None
    except OSError as refused:
        return refused



def _repo_root() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(top)


def _staged_violations(repo: Path, terms: Sequence[str]) -> list[Violation]:
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    return _scan(((rel, _staged_text(repo, rel)) for rel in filter(None, names)), terms)


def _staged_text(repo: Path, rel: str) -> str | None:
    blob = subprocess.run(
        ["git", "show", f":{rel}"], cwd=repo, capture_output=True, check=False,
    )
    if blob.returncode:
        return None
    try:
        return blob.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app_support.sanitize",
        description="Refuse a commit that carries a blocked term.")
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--staged", action="store_true",
                      help="Scan the staged changes (pre-commit).")
    what.add_argument("--message", metavar="FILE",
                      help="Scan a commit message file (commit-msg).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        repo = _repo_root()
    except (OSError, subprocess.SubprocessError):
        return 0
    path = blocklist_path(repo)
    terms = load_blocklist(path) if path.exists() else []
    if not terms:
        print(f"sanitize: no blocklist at {path}; nothing enforced", file=sys.stderr)
        return 0

    if args.message:
        text = Path(args.message).read_text(encoding="utf-8", errors="replace")
        what = "commit message"
        violations = find_violations(text, terms, path=args.message)
    else:
        what = "staged changes"
        violations = _staged_violations(repo, terms)
    if not violations:
        return 0

    print(f"blocked term in {what}:", file=sys.stderr)
    for v in violations[:_MOST_LISTED]:
        print(f"  {v.path}:{v.line}  {v.excerpt}", file=sys.stderr)
    if len(violations) > _MOST_LISTED:
        print(f"  ... {len(violations) - _MOST_LISTED} more", file=sys.stderr)
    print(
        "\nFabricate the value instead -- invent it from scratch rather than\n"
        "editing a real one, which leaves the same thing named. `--no-verify`\n"
        "skips this, and puts the term in history for good.",
        file=sys.stderr,
    )
    return 1
