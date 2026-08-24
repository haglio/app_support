"""Learn the blocklist off the machine, instead of remembering it by hand.

    python -m app_support.sanitize.harvest            # this checkout's list
    python -m app_support.sanitize.harvest --sync     # ...and every sibling's
    python -m app_support.sanitize.harvest --dry-run  # counts only, write nothing
    python -m app_support.sanitize.harvest --if-stale 12 --detach --sync   # startup

The guard can only refuse a term it has been told about, which leaves one hole it
cannot close on its own: a name nobody has ever added passes the hook, the suite
and CI alike. That is not hypothetical -- it is how every value that reached a
public ``main`` got there, and each one of them was a folder name or a filename
fragment sitting in a directory tree on this machine the whole time.

So harvest them. A value can only be copied into a fixture if it exists in that
tree, and if it exists there this can find it first. That turns the unknown-name
case into the known-term case the guard already enforces at commit time.

Everything that would make this module know what it is reading lives outside it,
in git-ignored files beside the blocklist -- because the words describe the
machine, and a committed copy of them would be the catalogue the guard exists to
keep out of the repo:

* ``library_roots.local.txt`` -- one directory to walk per line.
* ``harvest_excluded.local.txt`` -- ordinary words a name-shaped run is not worth
  blocking for. Without them the harvest would put the tree's own filing
  vocabulary onto a list that syncs to every checkout and fails all of them.
* ``harvest_suffixes.local.txt`` -- the file suffixes whose stems are worth
  reading a name off. Reading everything would harvest prose.

With any of the three missing there is nothing this can safely do, and it says so
and exits quietly. What stays here is only the shape of a name: two or more
capitalised words joined the way a filename joins them.

A list is only as good as its last run, so the run should not depend on anyone
remembering it. ``--if-stale HOURS`` returns immediately unless the last harvest
is older than that, and ``--detach`` hands the work to a background process and
returns at once -- together they make this safe to fire from anything that
starts, however often it starts, without a 50-second walk of the tree in front
of it.

Nothing here ever prints a harvested value. Counts only, the same rule the guard
follows for its own excerpts.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Collection

from app_support.sanitize.guard import blocklist_path, load_blocklist, scan_files

ROOTS_NAME = "library_roots.local.txt"
STAMP_NAME = "harvest_stamp.local.txt"
EXCLUDED_NAME = "harvest_excluded.local.txt"
SUFFIXES_NAME = "harvest_suffixes.local.txt"
# Deep enough for a few levels of filing above the files themselves, shallow
# enough that a stray archive folder does not turn into an all-night walk.
MAX_DEPTH = 6

# Two or more capitalized words joined the way a filename joins them: the shape
# a credit takes, and the shape every leak so far has had.
_CAPPED = r"[A-Z][A-Za-z']{2,}"
_NAME = re.compile(rf"\b({_CAPPED}(?:[ _.-]+{_CAPPED})+)")
_SPLIT = re.compile(r"[\s_.-]+")
# A credit usually leads, separated from the title by a spaced dash.
_CREDIT_BREAK = re.compile(r"\s[-–]\s")
# Past this a run is a title, not a name; the leading pair is the part worth
# having, and taking the whole thing would block a sentence.
_MAX_RUN_WORDS = 4


def normalize(raw: str) -> str:
    """A term as the blocklist writes it: lowercase, single-spaced words."""
    return " ".join(_SPLIT.split(raw.strip())).strip().lower()


def _is_useful(term: str, excluded: Collection[str]) -> bool:
    words = term.split()
    if term in excluded or any(w in excluded for w in words):
        return False
    if len(words) >= 2:
        return all(len(w) >= 3 for w in words)
    # A lone word has to earn its place: short ones and technical fragments
    # match far too much prose to be worth the false failures.
    return len(term) >= 6 and term.isalpha()


def candidates_from(
    name: str, *, whole_name_counts: bool, excluded: Collection[str],
) -> set[str]:
    """Terms worth blocking from one file stem or directory name.

    *whole_name_counts* is for directories: a folder at the bottom of the filing
    is named after one person and nothing else, so its own name is the term. A
    filename is a whole credit line, so only the name-shaped runs inside it are.

    From each run of capitalized words we keep the leading pair -- the credit,
    in ``Name - Title`` -- and the whole run only while it is still short enough
    to be a name rather than a sentence.

    *excluded* is the machine's own list of ordinary words: one of them anywhere
    in a run disqualifies the run, because a term already in everyday use fails
    innocent commits everywhere the moment it lands.
    """
    found: set[str] = set()
    credit = _CREDIT_BREAK.split(name)[0]
    for region in {name, credit}:
        for match in _NAME.finditer(region):
            words = normalize(match.group(1)).split()
            found.add(" ".join(words[:2]))
            if len(words) <= _MAX_RUN_WORDS:
                found.add(" ".join(words))
    if whole_name_counts:
        found.add(normalize(name))
    return {t for t in found if _is_useful(t, excluded)}


def harvest(
    roots: list[Path],
    *,
    excluded: Collection[str],
    suffixes: Collection[str],
    max_depth: int = MAX_DEPTH,
) -> set[str]:
    """Every name-shaped term under *roots*.

    From folder names, and from the stems of files whose suffix is one of
    *suffixes* -- reading every file's name instead would harvest whatever else
    happens to be filed there.
    """
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        base = len(root.parts)
        for path in root.rglob("*"):
            if len(path.parts) - base > max_depth:
                continue
            try:
                if path.is_dir():
                    found |= candidates_from(
                        path.name, whole_name_counts=True, excluded=excluded)
                elif path.suffix.lower() in suffixes:
                    found |= candidates_from(
                        path.stem, whole_name_counts=False, excluded=excluded)
            except OSError:
                continue
    return found


def already_in_code(candidates: set[str], repos: list[Path]) -> set[str]:
    """Candidates that already appear in tracked, published code.

    This is the safety valve, and it does the work no word list could. A folder
    called ``outputs`` or ``frames`` is a real folder name, but adding it
    would fail thousands of innocent lines the moment it landed -- and a term
    that is already sitting in a public repo is, by definition, not a secret.
    Every tracked tree is clean when this runs, so anything it finds is a
    collision with ordinary vocabulary rather than a leak.

    One pass over each tree with all candidates at once, since the alternative is
    hundreds of passes over the same files.
    """
    terms = sorted(candidates)
    if not terms:
        return set()
    collisions: set[str] = set()
    for repo in repos:
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files"],
            capture_output=True, text=True,
        ).stdout.split()
        remaining = [t for t in terms if t not in collisions]
        if not remaining:
            break
        found = scan_files((repo / rel for rel in tracked), remaining, root=repo)
        collisions |= {v.term for v in found}
    return collisions


def stamp_path(repo: Path) -> Path:
    """Where the last successful harvest recorded itself.

    Beside the blocklist, so it follows the same rule the blocklist does: one
    per machine, found from a worktree, and never committed.
    """
    return blocklist_path(repo).parent / STAMP_NAME


def hours_since_harvest(repo: Path) -> float | None:
    """Age of the last successful harvest in hours, or None if there wasn't one."""
    stamp = stamp_path(repo)
    try:
        return (time.time() - stamp.stat().st_mtime) / 3600
    except OSError:
        return None


def detach(argv: list[str]) -> None:
    """Re-run this script in the background and return immediately.

    A harvest walks the whole tree and takes the best part of a minute. That
    is fine in the background and unacceptable in front of anything a person is
    waiting on, so the callers that fire this on startup never wait for it. The
    child is fully detached: it outlives the session that started it, and its
    output goes nowhere, since the only thing it could print about a failure is
    a count.
    """
    flags = 0
    if sys.platform == "win32":  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200
    subprocess.Popen(
        [sys.executable, "-m", "app_support.sanitize.harvest",
         *[a for a in argv if a != "--detach"]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True,
    )


def read_roots(repo: Path) -> list[Path]:
    """Roots to walk, from the git-ignored overlay beside the blocklist."""
    listing = blocklist_path(repo).parent / ROOTS_NAME
    if not listing.exists():
        return []
    return [
        Path(line.strip())
        for line in listing.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def read_excluded(repo: Path) -> set[str] | None:
    """Ordinary words a harvested run is not worth blocking for, or None.

    None means the file is not there at all, which is a different answer from an
    empty list: an empty list is somebody deciding nothing needs excluding, and a
    missing file is a machine that was never set up. Reading the second as the
    first would put the words the tree is filed under onto a blocklist that syncs
    to every checkout at once, and turn all of them red.

    Entries are normalised the way a candidate is, so an entry written with
    capitals or dashes still matches.
    """
    listing = blocklist_path(repo).parent / EXCLUDED_NAME
    if not listing.exists():
        return None
    return {normalize(term) for term in load_blocklist(listing)}


def read_suffixes(repo: Path) -> set[str] | None:
    """File suffixes whose stems are worth reading a name off, or None if unset.

    A leading dot is optional in the file and always present in the answer, since
    ``Path.suffix`` carries one -- an entry without it would match nothing, and
    the failure would be a harvest that quietly reads fewer files.
    """
    listing = blocklist_path(repo).parent / SUFFIXES_NAME
    if not listing.exists():
        return None
    return {
        ("" if raw.startswith(".") else ".") + raw.lower()
        for raw in load_blocklist(listing)
    }


def merge(existing: list[str], harvested: set[str]) -> tuple[list[str], int]:
    """The blocklist with *harvested* folded in, and how many were new."""
    known = {normalize(t) for t in existing}
    fresh = sorted(t for t in harvested if t not in known)
    merged = sorted({*existing, *fresh}, key=str.lower)
    return merged, len(fresh)


HEADER = """\
# Pre-publication blocklist -- git-ignored on purpose: a committed copy would
# itself be a catalogue of what we keep out of a public repo.
# One term per line; '#' comments and blanks ignored. Matching is
# case-insensitive, word-boundaried, and tolerant of the separators and
# inflections real text uses -- write terms in prose form.
#
# Kept identical across every Haglio repo, so a term learned anywhere is
# enforced everywhere. Add to it with `python -m app_support.sanitize.harvest
# --sync`, which reads the roots named in library_roots.local.txt.
"""


def primary_of(repo: Path) -> Path:
    """The primary checkout *repo* belongs to, given a worktree or the primary.

    Worktrees share one git directory whose parent is the primary -- the same
    trick ``blocklist_path`` uses, needed here for the same reason.
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return repo
    return (repo / common).resolve().parent


def siblings_of(repo: Path) -> list[Path]:
    """Sibling checkouts that keep a blocklist of their own, plus the primary.

    Anchored on the primary checkout, never on *repo* itself. A worktree lives
    at ``<primary>/.claude/worktrees/<name>``, so its neighbours are other
    worktrees -- and everything here runs in a worktree. Taking those as the
    siblings quietly halved the job: the collision check saw a couple of
    checkouts instead of all eleven, so three ordinary project words survived it
    and turned three repos red the moment the list synced.
    """
    primary = primary_of(repo)
    return sorted(
        d for d in primary.parent.iterdir()
        if d.is_dir() and d != primary and (d / "sanitize").is_dir()
    )


def write_list(repo: Path, terms: list[str]) -> None:
    target = blocklist_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HEADER + "\n".join(terms) + "\n", encoding="utf-8")


def _stale_hours(argv: list[str]) -> float | None:
    """The ``--if-stale HOURS`` threshold, or None when the flag is absent."""
    if "--if-stale" not in argv:
        return None
    try:
        return float(argv[argv.index("--if-stale") + 1])
    except (IndexError, ValueError):
        return 24.0


def main(argv: list[str]) -> int:
    repo = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())

    overlay = blocklist_path(repo).parent
    roots = read_roots(repo)
    if not roots:
        print(f"no {ROOTS_NAME} beside the blocklist -- nothing to harvest.")
        print(f"Write one path per line into {overlay / ROOTS_NAME} to enable it.")
        return 0

    # Both checks come before any work: a startup caller fires this every time
    # it starts, and must pay nothing on the runs that have nothing to do.
    threshold = _stale_hours(argv)
    if threshold is not None:
        age = hours_since_harvest(repo)
        if age is not None and age < threshold:
            print(f"harvested {age:.1f}h ago, under the {threshold:g}h "
                  "threshold -- nothing to do.")
            return 0

    # Refusing to walk beats walking half-informed. Without the exclusions the
    # words the tree is filed under would land on a list that syncs to every
    # checkout; without the suffixes every file's name would be read as a name.
    # Before `--detach` and not after: a detached child's output goes to three
    # DEVNULLs, so this is the last point at which anyone can be told.
    excluded = read_excluded(repo)
    suffixes = read_suffixes(repo)
    absent = [name for name, got in
              ((EXCLUDED_NAME, excluded), (SUFFIXES_NAME, suffixes)) if got is None]
    if absent:
        print(f"no {' or '.join(absent)} beside the blocklist -- "
              "nothing safe to harvest.")
        for name in absent:
            print(f"Write one entry per line into {overlay / name}.")
        return 0

    if "--detach" in argv:
        detach(argv)
        return 0
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        print(f"{len(missing)} of {len(roots)} configured roots are not "
              "reachable right now; harvesting the rest.", file=sys.stderr)

    harvested = harvest(roots, excluded=excluded, suffixes=suffixes)
    # The primary, not this checkout: run from a worktree, `repo` has no
    # blocklist and shares its tracked files with the primary anyway.
    checkouts = [primary_of(repo), *siblings_of(repo)]
    collisions = already_in_code(harvested, checkouts)
    keep = harvested - collisions
    current = load_blocklist(blocklist_path(repo))
    merged, added = merge(current, keep)
    print(f"the walk yielded {len(harvested)} terms; "
          f"{len(collisions)} dropped as ordinary vocabulary already in code; "
          f"{added} new, list now {len(merged)}.")

    if "--dry-run" in argv:
        return 0
    home = primary_of(repo)
    write_list(home, merged)
    targets = [home.name]
    if "--sync" in argv:
        for sibling in siblings_of(repo):
            write_list(sibling, merged)
            targets.append(sibling.name)
    # Stamped only on a run that reached the end, so a harvest that died partway
    # is retried rather than treated as this window's run.
    stamp_path(repo).write_text("", encoding="utf-8")
    print(f"written to: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
