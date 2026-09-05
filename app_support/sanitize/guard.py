"""Pre-publication content guard.

Scans text for terms that must never reach a public commit — whatever the
machine's own list names: private vocabulary, filename fragments, provider and
site names, personal identifiers. The term list is deliberately *not* committed:
a checked-in blocklist would itself be a catalogue of the words we are trying to
keep out of the public repo.
Instead one list sits beside the family of checkouts, in no repository at all —
see ``blocklist_path``.

The module is dependency-free and importable without the app, so a repo's git
hooks and its unit suite can both call it cheaply — run it as
``python -m app_support.sanitize --staged`` or ``--message FILE``. Excerpts are
fully redacted (every matched term replaced with ``***``) so the guard's own
output never reproduces the content it is guarding against.
"""
from __future__ import annotations

import argparse
import bisect
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_MAX_EXCERPT = 160
_BLOCKLIST = Path(".sanitize") / "blocklist.txt"
# What may stand between the words of a multi-word term: any run of spacing or
# joining punctuation, or nothing — the shapes a filename uses.
_SEPARATOR = r"[\s\-_.]*"
# What a filename joins its words with; read as spaces when the name is scanned.
_NAME_JOINERS = re.compile(r"[\s\-_.]+")
# Trailing inflections a blocklist entry is not written with but text uses.
_INFLECTION = r"(?:'?s|es|ed|ing)?"


@dataclass(frozen=True)
class Violation:
    """One blocklisted term found at a location.

    The term stays out of the repr: a failing check reprints its violations
    through pytest's assertion introspection, into the terminal and into any
    retained junit artifact, and the term is the one thing this guard exists
    to keep out of both.  The excerpt is already redacted.
    """

    path: str
    line: int
    term: str = field(repr=False)
    excerpt: str


def _term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive matcher for *term*, in the forms text actually uses.

    A term whose first/last character is a word character gets a word-boundary
    guard on that side, so ``cat`` does not fire inside ``concatenate`` while a
    punctuated term like ``site.co`` still matches literally.

    The two things a plain literal misses are the two things that leak:

    * **Separators.** A blocklist is written in prose — ``two word`` — and the
      leak arrives as a filename: ``two-word``, ``two_word``, ``two.word``,
      ``twoword``. So the gaps between a term's words match any run of spacing
      or joining punctuation, including none at all.
    * **Inflections.** ``badterm`` on the list did not catch ``badterms`` in a
      README, because the trailing ``(?!\\w)`` refused the plural. A short
      inflectional tail is allowed before that boundary.

    Both widenings were measured against every tracked file in all eleven repos
    before landing: they added no false positive, and they caught real names that
    had been sitting on a public ``main`` in slug form.
    """
    stripped = term.strip()
    parts = stripped.split()
    core = _SEPARATOR.join(re.escape(p) for p in parts) if parts else re.escape(stripped)
    left = r"(?<!\w)" if stripped[:1].isalnum() or stripped[:1] == "_" else ""
    right = r"(?!\w)" if stripped[-1:].isalnum() or stripped[-1:] == "_" else ""
    return re.compile(left + core + _INFLECTION + right, re.IGNORECASE)


def _compile(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    return [(t.strip(), _term_pattern(t)) for t in terms if t.strip()]


def _redact(line: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> str:
    out = line
    for _term, pat in patterns:
        out = pat.sub("***", out)
    return out.strip()[:_MAX_EXCERPT]


def find_violations(
    text: str,
    terms: Iterable[str],
    *,
    path: str = "<text>",
) -> list[Violation]:
    """Every blocklisted term occurrence in *text*, one per (line, term).

    Matched against the whole text rather than line by line, because a term's
    words are separated by *any* whitespace — a newline included — so a
    multi-word term that a wrap has split across two lines is a real occurrence
    that a per-line scan cannot see. One was: a title broken over a docstring's
    line break survived every scan until a history rewrite, matching on the whole
    blob, put it back together.

    The line reported is where the match *starts*, and the excerpt is that line,
    so a wrapped hit still points at somewhere useful to look.
    """
    patterns = _compile(terms)
    lines = text.splitlines()
    # Offset of each line start, to turn a match position into a line number.
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line) + 1
    out: list[Violation] = []
    for term, pat in patterns:
        for match in pat.finditer(text):
            lineno = bisect.bisect_right(starts, match.start())
            excerpt = _redact(lines[lineno - 1], patterns) if lines else ""
            out.append(Violation(path, lineno, term, excerpt))
    out.sort(key=lambda v: (v.line, v.term))
    return out


def blocklist_path(repo: Path) -> Path:
    """The one list, beside the checkouts rather than inside any of them.

    The list describes the machine, not a tree, so a copy per repository was
    always the wrong shape: eleven of them had to be edited in lockstep to stay
    one list, and nothing made them. Beside the family it is one file, and being
    outside every repository is what makes it uncommittable — a stronger promise
    than the ``.gitignore`` line each copy used to rely on.

    ``git rev-parse --git-common-dir`` names the primary checkout's git
    directory, which every worktree shares, so two levels up from it is the
    directory the checkouts sit in. Resolving from the worktree's own path
    instead would land two levels too deep, which is how the tracked-tree check
    was once a silent no-op in exactly the place all the work happens.

    The leading dot says what the directory is: everything else beside it is a
    checkout, and this one is not.

    The returned path need not exist — a public clone legitimately has no
    blocklist, and so does a source tree with no git at all. Callers check
    ``.exists()`` and treat absence as nothing to enforce.
    """
    try:
        common_dir = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return repo.resolve().parent / _BLOCKLIST
    return (repo / common_dir).resolve().parent.parent / _BLOCKLIST


def load_blocklist(path: Path) -> list[str]:
    """Read a blocklist file: one term per line, ``#`` comments and blanks skipped."""
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def _safe_name(path: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> str:
    """*path* as a report may show it: itself, unless its name carries a term.

    A name joins its words with ``_``, ``-`` and ``.``, which the matcher's word
    boundaries read as letters, so the name is judged with those as spaces --
    and a name that carries a term is shown in that reading, redacted, since
    the report and pytest's introspection would otherwise print the term.
    """
    words = _NAME_JOINERS.sub(" ", path)
    if any(pat.search(words) for _term, pat in patterns):
        return _redact(words, patterns)
    return path


def name_violations(path: str, terms: Iterable[str]) -> list[Violation]:
    """Every blocklisted term in a file's *name*, reported at line 0.

    A name is text the repository publishes as surely as any file's contents,
    and it used to be passed through as a label and never scanned -- which is
    how a launcher named after a term cleared every guard and reached a
    public ``main``.  The path is reported redacted (:func:`_safe_name`).
    """
    patterns = _compile(terms)
    words = _NAME_JOINERS.sub(" ", path)
    return [Violation(_safe_name(path, patterns), 0, term, "(in the file's name)")
            for term, pat in patterns if pat.search(words)]


def scan_files(
    paths: Iterable[Path],
    terms: Iterable[str],
    *,
    root: Path | None = None,
) -> list[Violation]:
    """Scan each file's name, and each readable text file's contents, for
    blocklisted terms.

    Binary or undecodable contents are skipped — assets are excluded from a
    public repo by ``.gitignore``, not by this text guard — but every name is
    read.
    """
    terms = list(terms)
    patterns = _compile(terms)
    out: list[Violation] = []
    for path in paths:
        display = str(path.relative_to(root)) if root else str(path)
        out.extend(name_violations(display, terms))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out.extend(find_violations(text, terms, path=_safe_name(display, patterns)))
    return out


# --------------------------------------------------------------------------
# Command line, for each repo's git hooks.
#
# A hook catches a term while it is still staged, which is the only point at
# which the fix is free. The unit suite catches the same term afterwards, and by
# then it is already a commit -- and on a public repo, a commit is forever: a
# history rewrite is partial protection at best, since unreferenced objects stay
# reachable for a while and clones, forks and caches outlive the rewrite.
# --------------------------------------------------------------------------


def _repo_root() -> Path:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(top)


def _staged_violations(repo: Path, terms: Sequence[str]) -> list[Violation]:
    """Blocklist hits in what is *staged*, read from the index rather than disk.

    The index is what the commit will contain: a partially-staged file must be
    judged on the staged half, not on the working copy sitting next to it.
    """
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    patterns = _compile(terms)
    out: list[Violation] = []
    for rel in filter(None, names):
        out.extend(name_violations(rel, terms))
        blob = subprocess.run(
            ["git", "show", f":{rel}"], cwd=repo, capture_output=True, check=False,
        )
        if blob.returncode:
            continue
        try:
            text = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
        out.extend(find_violations(text, terms, path=_safe_name(rel, patterns)))
    return out


def build_parser() -> argparse.ArgumentParser:
    """The two flags the hooks pass.

    argparse, not a scan of ``sys.argv``: this runs inside a git hook, where a
    missing value for ``--message`` used to be an IndexError.
    """
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
    """``--staged`` for pre-commit, ``--message FILE`` for commit-msg.

    Exits 0 when there is no blocklist to enforce, so a public clone and a
    checkout without the overlay both commit normally. The flags are parsed
    first, before that check: a hook calling this wrongly must hear about it in
    the checkout where the guard has nothing to enforce as well as in the one
    where it does.
    """
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        repo = _repo_root()
    except (OSError, subprocess.SubprocessError):
        return 0
    path = blocklist_path(repo)
    terms = load_blocklist(path) if path.exists() else []
    if not terms:
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

    # Report the redacted excerpt only; naming the term would print the content
    # this guard exists to keep out of the terminal as well as the repo.
    print(f"blocked term in {what}:", file=sys.stderr)
    for v in violations[:20]:
        print(f"  {v.path}:{v.line}  {v.excerpt}", file=sys.stderr)
    if len(violations) > 20:
        print(f"  ... {len(violations) - 20} more", file=sys.stderr)
    print(
        "\nFabricate the value instead -- invent it from scratch rather than\n"
        "editing a real one, which leaves the same thing named. `--no-verify`\n"
        "skips this, and puts the term in history for good.",
        file=sys.stderr,
    )
    return 1
