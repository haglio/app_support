"""The one check whose subject is the repository under test, not this package.

Shipped, not collected: ``app_support.sanitize.pytest_plugin`` hands this file to
pytest, so a repo gets the enforcement by naming the plugin once rather than by
keeping a copy of it. See that module for why it is opt-in.
"""
from __future__ import annotations

import subprocess
import warnings
from pathlib import Path

import pytest

from app_support.sanitize.guard import blocklist_path, load_blocklist, scan_files


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


def test_no_blocklisted_terms_in_the_tracked_tree(pytestconfig):
    """Enforcement: with the real (git-ignored) blocklist present, no tracked
    file may contain a banned term — reintroducing one fails the suite.
    """
    repo = _repo_under_test(pytestconfig.rootpath)
    blocklist = blocklist_path(repo)
    terms = load_blocklist(blocklist) if blocklist.exists() else []
    if not terms:
        _say_the_tree_was_not_scanned(blocklist)
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    # A walk that read nothing reports "passed" in the same words as a walk that
    # read the tree, and only one of them means anything. git having succeeded is
    # not enough: an empty list is the shape a scan of nothing arrives in.
    assert tracked, "the tracked-tree walk saw no files at all"
    violations = scan_files((repo / rel for rel in tracked), terms, root=repo)
    # Print only the redacted excerpt, never the matched term itself.
    assert not violations, "blocklisted terms in tracked files:\n" + "\n".join(
        f"  {v.path}:{v.line}  {v.excerpt}" for v in violations[:20]
    )
