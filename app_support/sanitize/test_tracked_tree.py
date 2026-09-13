"""The one check whose subject is the repository under test, not this package.

Shipped, not collected: ``app_support.sanitize.pytest_plugin`` hands this file to
pytest, so a repo gets the enforcement by naming the plugin once rather than by
keeping a copy of it. See that module for why it is opt-in.
"""
from __future__ import annotations

import re
import subprocess
import warnings
from collections.abc import Sequence
from pathlib import Path

import pytest

from app_support.sanitize.guard import (
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
)

# A whole word of letters, with a non-word character on each side.  Both halves
# are what keep the control clear of the matcher's edges rather than sitting on
# them: `_matcher` puts a word boundary around a term whose first and last
# characters are word characters, so a control taken from inside a longer word
# would be refused by the very rule being proved, and a run of letters carries
# none of the separator collapsing a term with digits or punctuation in it does.
_A_WHOLE_WORD = re.compile(r"(?<!\w)[A-Za-z]{4,}(?!\w)")


def _repo_under_test(rootpath: Path) -> Path:
    """The checkout pytest is running against.

    ``rootpath`` is where pytest found its configuration, which is the repo root
    in every one of these repos but need not be -- so the checkout is whatever
    git says it is from there, and only failing that is the root itself taken at
    its word.
    """
    try:
        top = subprocess.run(
            ["git", "-C", str(rootpath), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return Path(rootpath)
    return Path(top) if top else Path(rootpath)


def _say_the_tree_was_not_scanned(blocklist: Path) -> None:
    """No terms resolved, so nothing was scanned. Report that, do not pass.

    This used to `return`, and the docstring called it deliberate — "so the run
    stays clean either way". That is what made the check a silent no-op on every
    merge queue in the family: CI checks out the public repository, which by
    design carries no blocklist, so the one place a commit is stopped before it
    lands scanned nothing and logged a pass indistinguishable from a scanned
    tree.

    It still must not take a run down. A public clone, a source archive and a
    stripped CI checkout all legitimately arrive without the overlay, and a
    plugin that failed there would be removed from every repo that adopted it.
    So it warns and skips: the exit code is unchanged, the summary says
    "1 skipped" rather than "1 passed", and the reason travels in the warnings
    summary, which `pytest -q` prints without the `-rs` the family's gates do
    not pass. Enforcement lives where the blocklist lives.
    """
    unscanned = (
        f"the tracked tree was NOT scanned: no blocklist terms resolved at {blocklist}"
    )
    warnings.warn(f"SANITIZE GUARD UNARMED: {unscanned}", stacklevel=2)
    pytest.skip(unscanned)


def _a_control_word_from(paths: Sequence[Path], terms: Sequence[str]) -> str | None:
    """A word the consumer's own tracked tree carries, to plant in the scan.

    The check's own negative control, and the one thing it could not otherwise
    have: the shipped file lives in an installed package that appears in no
    consumer's ``git ls-files``, so a term planted in *this* source proves only
    that this source was read.  A word taken out of the tree under test cannot
    come back from a walk that stopped reading that tree.

    Chosen to sit well inside the matcher's rules rather than on their edges
    (:data:`_A_WHOLE_WORD`), and never a word ending in ``s``: a term in the
    plural is compiled from its stem, so the string the scan looks for would
    stop being the string read here.  A word that itself carries a blocklisted
    term is passed over, so a real hit can never be mistaken for the control.

    ``None`` when no tracked file could be read at all -- which is the state
    this control exists to tell apart from a clean tree.
    """
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in _A_WHOLE_WORD.finditer(text):
            word = match.group()
            if word.lower().endswith("s") or find_violations(word, terms):
                continue
            return word
    return None


def test_no_blocklisted_terms_in_the_tracked_tree(pytestconfig):
    """Enforcement: with the real (git-ignored) blocklist present, no tracked
    file may contain a banned term — reintroducing one fails the suite.
    """
    repo = _repo_under_test(pytestconfig.rootpath)
    blocklist = blocklist_path(repo)
    terms = load_blocklist(blocklist) if blocklist.exists() else []
    if not terms:
        _say_the_tree_was_not_scanned(blocklist)
    # NUL-separated, and never split on whitespace: a tracked name carrying a
    # space became two paths that way, neither of which exists -- and a path
    # that cannot be read is skipped in silence, so the file was invisible to
    # the scan while the run stayed green.  `-z` also drops git's own quoting
    # of such a name, which would have been the next way to miss it.
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    tracked = [repo / rel for rel in listed.split("\0") if rel]
    # A walk that read nothing reports "passed" in the same words as a walk that
    # read the tree, and only one of them means anything. git having succeeded is
    # not enough: an empty list is the shape a scan of nothing arrives in.
    assert tracked, "the tracked-tree walk saw no files at all"
    control = _a_control_word_from(tracked, terms)
    assert control is not None, (
        f"the tracked-tree walk read no text at all: git named {len(tracked)} "
        f"files under {repo} and none of them could be read"
    )
    violations = scan_files(tracked, [*terms, control], root=repo)
    # The control goes through the same scan as the real terms, so what is
    # proved is the scan that reported, not a second one run beside it.
    assert any(v.term == control for v in violations), (
        f"the scan came back without the control word carried out of {repo}, "
        "so it did not read the tree it is reporting on"
    )
    # Print only the redacted excerpt, never the matched term itself.
    real = [v for v in violations if v.term != control]
    assert not real, (
        "tracked files that carry a blocklisted term or could not be read:\n"
        + "\n".join(f"  {v.path}:{v.line}  {v.excerpt}" for v in real[:20])
    )
