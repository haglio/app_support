"""The family's dead-code gate, published once instead of copied eleven times.

Every repo here answers "has anything stopped being used?" with vulture, and
eight of them had grown their own arrangement of the same subprocess call: six
shapes and three whitelist conventions. Counted rather than assumed: **seven of
the eight report a clean tree for a directory that holds no Python at all**
(evolver is the one that already asserts it found sources), and **one of them
reports a clean tree when vulture is not installed** -- the four that compare an
exit code to zero fail that case instead, with a message reading "Vulture found
dead code:" and then nothing. A repo asks for the gate in a few lines instead::

    # tests/test_dead_code.py
    from app_support.dead_code import assert_no_dead_code

    ROOT = Path(__file__).resolve().parent.parent

    def test_no_dead_code():
        assert_no_dead_code(ROOT / "the_package", whitelist=ROOT / "vulture_whitelist.py")

Name the production directories rather than scanning ``.`` under an
``--exclude`` list. vulture matches those patterns against absolute paths, and
an agent's checkout lives at ``<repo>/.claude/worktrees/<name>`` -- so
``--exclude .claude`` matches the root of the tree being scanned and excludes
every file in it, which is precisely the no-op this module exists to make
impossible.

vulture is a dev dependency of the repo asking for the gate, not of this
package: nothing here imports it, and this package installs into every app's
venv where a scanner has no business being.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from app_support import lint

# vulture's exit codes: 0 nothing to report, 3 the report is not empty. Every
# other code means it did not get as far as an answer -- 1 for input it could
# not read, 2 for arguments it could not parse, and 1 again from the interpreter
# when vulture is not installed at all.
_NOTHING_TO_REPORT = 0
_REPORT_IS_NOT_EMPTY = 3


class ScanDidNotRun(RuntimeError):
    """vulture never reached an answer, so silence here means nothing."""


def _refuse_a_target_with_nothing_to_read(targets: tuple[Path | str, ...]) -> None:
    """The failure no exit code reports: a target with no Python under it.

    vulture is content to be handed a directory holding nothing it can read and
    exits 0 for it, which is the same answer a scanned-and-clean tree gets. A
    gate whose target has moved, been renamed, or been swallowed by an
    ``--exclude`` that matched more than its author meant then passes for the
    rest of its life while scanning nothing at all.
    """
    for target in targets:
        path = Path(target)
        if not path.exists():
            raise ScanDidNotRun(f"nothing to scan: {path} does not exist")
        if path.is_dir() and next(path.rglob("*.py"), None) is None:
            raise ScanDidNotRun(f"nothing to scan: no Python under {path}")


def _refuse_a_whitelist_inside_the_scan(
    targets: tuple[Path | str, ...], whitelist: Path | str
) -> None:
    """Where a whitelist may not live.

    vulture reads the file by unioning the names it uses with the names the
    scanned tree uses, so one kept inside a scanned directory is read as part of
    that tree whether or not it was handed over -- and the gate then reports
    nothing at all, whatever the tree holds. Keep it beside the repo root, the
    way every repo in this family already does.
    """
    kept = Path(whitelist).resolve()
    for target in targets:
        directory = Path(target).resolve()
        if directory in kept.parents:
            raise ScanDidNotRun(
                f"the whitelist {kept} is inside {directory}, which is scanned. "
                "Every name in it would count as used and the gate could not "
                "report anything; keep it outside the trees it applies to."
            )


def scan(
    *targets: Path | str,
    whitelist: Path | str | None = None,
    min_confidence: int = 60,
) -> str:
    """vulture's report over *targets*; empty when there is nothing to report.

    *whitelist* is a Python file naming the exceptions a repo has decided on --
    framework callbacks, attributes read by something vulture cannot follow. It
    is handed to vulture as one more thing to scan, so a name mentioned there
    counts as used.

    Raises `ScanDidNotRun` rather than returning that same empty string when the
    scan did not happen. The two are the whole difficulty: a gate that reads
    "vulture is not installed" or "that directory is gone" as a clean tree is
    green for the rest of its life.
    """
    if whitelist is not None:
        _refuse_a_whitelist_inside_the_scan(targets, whitelist)
        targets = (*targets, whitelist)
    _refuse_a_target_with_nothing_to_read(targets)
    command = [sys.executable, "-m", "vulture",
               *(str(target) for target in targets),
               "--min-confidence", str(min_confidence)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == _REPORT_IS_NOT_EMPTY:
        return result.stdout
    if result.returncode != _NOTHING_TO_REPORT:
        raise ScanDidNotRun(
            f"vulture exited {result.returncode} instead of scanning:\n"
            f"  {' '.join(command)}\n{result.stdout}{result.stderr}"
        )
    return ""


def _reports(targets, whitelist, min_confidence, each_alone) -> str:
    """vulture's report over *targets* -- one run, or one run per target.

    Scanned together, packages hide each other's corpses: vulture matches by
    bare name across everything it is handed, so a function dead in one package
    is invisible while any other has a live name like it. One run each is
    narrower, and costs the cross-package readers, which the whitelist names.
    """
    if not each_alone:
        return scan(*targets, whitelist=whitelist, min_confidence=min_confidence)
    return "".join(scan(target, whitelist=whitelist, min_confidence=min_confidence)
                   for target in targets)


def assert_no_dead_code(
    *targets: Path | str,
    whitelist: Path | str | None = None,
    min_confidence: int = 60,
    each_alone: bool = False,
) -> None:
    """Fail the suite with vulture's report over *targets*."""
    report = _reports(targets, whitelist, min_confidence, each_alone)
    assert not report, (
        "vulture found dead code. Delete it, or -- if the caller is a framework "
        "vulture cannot see -- add the name to the whitelist with a comment "
        f"saying who calls it:\n{report}"
    )


# `vulture --make-whitelist` spells an attribute `_.name`, so `_` is the file's
# placeholder for "some object" and never an entry of its own.
_WHITELIST_PLACEHOLDER = "_"


def _names_the_whitelist_suppresses(whitelist: Path | str) -> set[str]:
    """Every name mentioned in the whitelist file, however it is spelled.

    vulture takes the file as source and unions the names it uses with the ones
    the scanned tree uses, so a mention is the whole mechanism -- ``_.name`` for
    an attribute or method, a bare name for anything else.
    """
    tree = ast.parse(Path(whitelist).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name) and node.id != _WHITELIST_PLACEHOLDER:
            names.add(node.id)
    return names


def _names_the_report_carries(report: str) -> set[str]:
    return set(re.findall(r"unused \w+ '([^']+)'", report))


def assert_whitelist_is_live(
    *targets: Path | str,
    whitelist: Path | str,
    min_confidence: int = 60,
    each_alone: bool = False,
) -> None:
    """Fail on a whitelist entry that no longer suppresses anything.

    The file records the exceptions a repo decided on, so an entry whose subject
    was deleted is not merely tidy-able: it is a standing exemption for whatever
    name happens to match it next. One repo in this family reached 31 dead
    entries out of 45, 23 of them naming symbols the family no longer contains,
    and its gate could not see what its own deletions had made stale.
    """
    _refuse_a_whitelist_inside_the_scan(targets, whitelist)
    report = _reports(targets, None, min_confidence, each_alone)
    stale = sorted(
        _names_the_whitelist_suppresses(whitelist) - _names_the_report_carries(report)
    )
    assert not stale, (
        f"{Path(whitelist).name} suppresses names vulture no longer reports. "
        "Delete these entries -- each one is an exemption waiting for the next "
        "name that happens to match it:\n"
        + "\n".join(f"  {name}" for name in stale)
    )


def packages_under(root) -> set[str]:
    """Every top-level package beside *root*: a directory with an ``__init__.py``
    whose name is not hidden or private."""
    return {
        path.name for path in Path(root).iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
        and not path.name.startswith((".", "_"))
    }


def assert_every_package_is_scanned(root, scanned, *, ignoring=("tests",)) -> None:
    """Fail on a top-level package the gate does not name.

    A package added beside the named ones would otherwise get no gate at all,
    which is how one repo's ``tools/`` came to hold 699 lines nothing scanned.
    """
    unnamed = sorted(packages_under(root) - set(scanned) - set(ignoring))
    assert not unnamed, (
        "packages beside the scanned ones that no gate names: "
        + ", ".join(unnamed) + ". Name them in the scan, or in `ignoring` with a reason."
    )


# The ruff rules that name dead code and nothing else: an import nothing uses, a
# redefinition that shadows the first, a local assigned and never read.
DEAD_CODE_LINT_RULES = ("F401", "F811", "F841")

# A parameter the body never reads, one level out from the constructor scan in
# `app_support.unread`. ARG001 alone by default: a framework override (Qt's
# paintEvent, a player's pump) is handed arguments it is free to ignore.
UNREAD_ARGUMENT_RULES = ("ARG001",)


def assert_nothing_is_imported_or_assigned_and_left_unread(root, *targets) -> None:
    """The blind spot vulture has: deadness local to one module.

    vulture resolves names across the whole tree it is handed, so an import
    unused HERE but live in a sibling module never reports. ruff answers per
    file, under these rules alone, whatever the repo's own config ratchets.
    """
    found = lint.findings_for_rules(root, DEAD_CODE_LINT_RULES, *targets)
    assert not found, "ruff found dead code:\n" + "\n".join(found)


def assert_no_function_takes_an_argument_it_never_reads(
    root, *targets, rules=UNREAD_ARGUMENT_RULES,
) -> None:
    """A signature that asks for something it does not use is a lie."""
    found = lint.findings_for_rules(root, rules, *targets)
    assert not found, "ruff found unread arguments:\n" + "\n".join(found)
