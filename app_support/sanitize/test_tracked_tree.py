from __future__ import annotations

import re
import subprocess
import warnings
from collections.abc import Sequence
from pathlib import Path

import pytest

from app_support.sanitize.guard import (
    Violation,
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
)

pytestmark = pytest.mark.repo_check

_A_WORD_WELL_INSIDE_THE_MATCHERS_RULES = re.compile(r"(?<!\w)[A-Za-z]{4,}(?!\w)")


def _repo_under_test(rootpath: Path) -> Path:
    try:
        top = subprocess.run(
            ["git", "-C", str(rootpath), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return Path(rootpath)
    return Path(top) if top else Path(rootpath)


def _say_the_tree_was_not_scanned(blocklist: Path) -> None:
    unscanned = (
        f"the tracked tree was NOT scanned: no blocklist terms resolved at {blocklist}"
    )
    warnings.warn(f"SANITIZE GUARD UNARMED: {unscanned}", stacklevel=2)
    pytest.skip(unscanned)


def _a_control_word_from(paths: Sequence[Path], terms: Sequence[str]) -> str | None:
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in _A_WORD_WELL_INSIDE_THE_MATCHERS_RULES.finditer(text):
            word = match.group()
            if word.lower().endswith("s") or find_violations(word, terms):
                continue
            return word
    return None


def _one_scan_of_the_terms_and_the_control(tracked: Sequence[Path], terms: Sequence[str], control: str,
                                           repo: Path, *, scan=scan_files) -> list[Violation]:
    return scan(tracked, [*terms, control], root=repo)


def test_no_blocklisted_terms_in_the_tracked_tree(pytestconfig):
    repo = _repo_under_test(pytestconfig.rootpath)
    blocklist = blocklist_path(repo)
    terms = load_blocklist(blocklist) if blocklist.exists() else []
    if not terms:
        _say_the_tree_was_not_scanned(blocklist)
    # git ls-files -z: a tracked name with a space would otherwise split into two unreadable paths, skipped silently.
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    tracked = [repo / rel for rel in listed.split("\0") if rel]
    assert tracked, "the tracked-tree walk saw no files at all"
    control = _a_control_word_from(tracked, terms)
    assert control is not None, (
        f"the tracked-tree walk read no text at all: git named {len(tracked)} "
        f"files under {repo} and none of them could be read"
    )
    violations = _one_scan_of_the_terms_and_the_control(tracked, terms, control, repo)
    assert any(v.term == control for v in violations), (
        f"the scan came back without the control word carried out of {repo}, "
        "so it did not read the tree it is reporting on"
    )
    real = [v for v in violations if v.term != control]
    assert not real, (
        "tracked files that carry a blocklisted term or could not be read:\n"
        + "\n".join(f"  {v.path}:{v.line}  {v.excerpt}" for v in real[:20])
    )
