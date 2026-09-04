"""The family's ruff config and lint gate, published once instead of copied eleven times.

A repo adopts both in a few lines::

    # tests/test_lint.py
    from app_support.lint import assert_config_is_the_familys, assert_lint_is_clean

    ROOT = Path(__file__).resolve().parent.parent

    def test_the_ruff_config_is_the_familys():
        assert_config_is_the_familys(ROOT / "ruff.toml")

    def test_ruff_finds_nothing():
        assert_lint_is_clean(ROOT, ROOT / "the_package", ROOT / "tests")

and commits the `ruff.toml` that `render_config` writes: the family's numbers, plus
the repo's own ratchet -- the rules the config found there on the day it was adopted,
to be worked off one at a time. The config test refuses a file that drifted anywhere
else, so there is one config, held here, and eleven copies of it that cannot differ.

ruff is a dev dependency of the repo asking for the gate, pinned to `RUFF_VERSION`,
never a dependency of this package.
"""
from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RUFF_VERSION = "0.16.6"

FAMILY_IGNORES = ("E501", "BLE001", "S110")

# Rule families other gates in this family run with selects of their own (genau's
# argument scan is ARG) or that only ever existed as markers here: a noqa for one
# is dormant, not unused, and RUF100 leaves it for the gate that reads it.
READ_BY_OTHER_GATES = ("ARG", "N", "S")

_SELECT = ("F", "E", "W", "I", "UP", "B", "C4", "SIM", "RUF", "PL", "PT", "DTZ", "PIE",
           "PERF", "FLY", "ISC", "RET", "FURB", "EXE")

_A_FINDING = re.compile(r"^.+?:\d+:\d+: [A-Z]+\d+ ")


def _quoted(codes) -> str:
    return ", ".join(f'"{code}"' for code in codes)


def render_config(ratchet=()) -> str:
    """The `ruff.toml` a repo commits: the family's numbers, then *ratchet* --
    that repo's own rules-to-work-off -- appended to the ignore list."""
    ignores = _quoted(FAMILY_IGNORES)
    if ratchet:
        ignores += (
            ",\n    # This repo's ratchet: what the family config found here, "
            "to be worked off rule by rule.\n    " + _quoted(ratchet)
        )
    return (
        "line-length = 100\n"
        'target-version = "py312"\n'
        "\n"
        "[lint]\n"
        f"select = [{_quoted(_SELECT)}]\n"
        f"ignore = [{ignores}]\n"
        f"external = [{_quoted((*READ_BY_OTHER_GATES, *FAMILY_IGNORES, *ratchet))}]\n"
        "\n"
        "[format]\n"
        'quote-style = "double"\n'
    )


def ratchet_of(ruff_toml) -> tuple[str, ...]:
    """The rules a repo's `ruff.toml` ignores beyond the family's own."""
    text = Path(ruff_toml).read_text(encoding="utf-8")
    ignored = tomllib.loads(text).get("lint", {}).get("ignore", [])
    return tuple(code for code in ignored if code not in FAMILY_IGNORES)


def assert_config_is_the_familys(ruff_toml) -> None:
    """*ruff_toml* is `render_config` of its own ratchet, byte for byte."""
    written = Path(ruff_toml).read_text(encoding="utf-8")
    expected = render_config(ratchet_of(ruff_toml))
    if written != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), written.splitlines(keepends=True),
            "the family's", str(ruff_toml)))
        raise AssertionError(
            f"{ruff_toml} is not the family's ruff config plus this repo's ratchet:\n{diff}")


class LintDidNotRun(RuntimeError):
    """ruff never reached an answer, so silence here means nothing."""


def _ruff(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ruff", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", check=False)


def ruff_version(root) -> str:
    ran = _ruff(root, "--version")
    if ran.returncode != 0:
        raise LintDidNotRun(f"ruff is not installed for {sys.executable}:\n{ran.stderr}")
    return ran.stdout.split()[-1]


def scan_targets(root, trees) -> list[str]:
    """What the gate hands ruff: the named *trees* and the root's own files.

    Never `.`: a gate checks out sibling repos beside or inside this one
    (player_core's runner puts shared_ui under it) and an agent's checkout lives
    in `.claude/worktrees`, and all of it would be read under this repo's config.
    """
    return [str(tree) for tree in trees] + [path.name for path in sorted(Path(root).glob("*.py"))]


def files_seen(root, targets) -> list[Path]:
    """What ruff would scan of *targets* under *root*, its config's excludes applied."""
    ran = _ruff(root, "check", "--show-files", *targets)
    if ran.returncode != 0:
        raise LintDidNotRun(f"ruff could not list {root}:\n{ran.stdout}{ran.stderr}")
    return [Path(line) for line in ran.stdout.splitlines() if line.strip()]


def findings(root, targets) -> list[str]:
    """ruff's findings in *targets* under *root*, one concise line each; empty when
    it found nothing.

    Raises `LintDidNotRun` rather than returning that same empty list when ruff
    did not scan: not installed, another version than the family's, or a
    configuration it refused.
    """
    version = ruff_version(root)
    if version != RUFF_VERSION:
        raise LintDidNotRun(f"ruff {version} is not the family's {RUFF_VERSION}; pin it in [dev]")
    ran = _ruff(root, "check", "--no-fix", "--output-format", "concise", *targets)
    if ran.returncode not in (0, 1):
        raise LintDidNotRun(f"ruff exited {ran.returncode} instead of scanning {root}:\n"
                            f"{ran.stdout}{ran.stderr}")
    return [line for line in ran.stdout.splitlines() if _A_FINDING.match(line)]


def _refuse_a_scan_that_skipped(root, trees, targets) -> None:
    """The failure no exit code reports: a tree the config's excludes or the
    gitignore swallowed whole, which scans clean for the rest of its life."""
    seen = files_seen(root, targets)
    for tree in trees:
        wanted = Path(tree).resolve()
        if not any(wanted in path.resolve().parents for path in seen):
            raise LintDidNotRun(f"ruff scanned nothing under {wanted}")


def assert_lint_is_clean(root, *trees) -> None:
    """ruff finds nothing in *trees* or in the root's own files, having scanned at
    least one file under each tree."""
    targets = scan_targets(root, trees)
    _refuse_a_scan_that_skipped(root, trees, targets)
    found = findings(root, targets)
    if found:
        raise AssertionError(
            f"ruff found {len(found)} thing(s) under {root}:\n" + "\n".join(found))
