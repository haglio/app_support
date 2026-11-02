from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

from app_support import lint, unread

# vulture exits 0 for nothing to report and 3 for a report; 1 (unreadable input, or the interpreter
# when vulture is not installed) and 2 (unparsable arguments) mean it gave no answer.
_NOTHING_TO_REPORT = 0
_REPORT_IS_NOT_EMPTY = 3


class ScanDidNotRun(RuntimeError):
    pass


def _refuse_a_target_with_nothing_to_read(targets: tuple[Path | str, ...]) -> None:
    """vulture exits 0 for a directory holding no Python, the same as for a clean tree."""
    for target in targets:
        path = Path(target)
        if not path.exists():
            raise ScanDidNotRun(f"nothing to scan: {path} does not exist")
        if path.is_dir() and next(path.rglob("*.py"), None) is None:
            raise ScanDidNotRun(f"nothing to scan: no Python under {path}")


def _refuse_a_whitelist_inside_the_scan(
    targets: tuple[Path | str, ...], whitelist: Path | str
) -> None:
    """vulture unions the names a whitelist mentions with the scanned tree, even for one inside it."""
    kept = Path(whitelist).resolve()
    for target in targets:
        directory = Path(target).resolve()
        if directory in kept.parents:
            raise ScanDidNotRun(
                f"the whitelist {kept} is inside {directory}, which is scanned. "
                "Every name in it would count as used and the gate could not "
                "report anything; keep it outside the trees it applies to."
            )


def _refuse_a_target_inside_a_caller(
    targets: tuple[Path | str, ...], callers: tuple[Path, ...]
) -> None:
    for target in targets:
        path = Path(target).resolve()
        for caller in callers:
            if path == caller or caller in path.parents:
                raise ScanDidNotRun(
                    f"{path} is inside {caller}, which is read as a caller and left out of the report"
                )


def scan(
    *targets: Path | str,
    whitelist: Path | str | None = None,
    min_confidence: int = 60,
    callers: Iterable[Path | str] = (),
) -> str:
    callers = tuple(Path(caller).resolve() for caller in callers)
    _refuse_a_target_inside_a_caller(targets, callers)
    if whitelist is not None:
        _refuse_a_whitelist_inside_the_scan(targets, whitelist)
        targets = (*targets, whitelist)
    _refuse_a_target_with_nothing_to_read(targets)
    with tempfile.TemporaryDirectory() as scratch:
        config = Path(scratch) / "pyproject.toml"
        config.write_text(_vulture_config_reading(*targets, *callers), encoding="utf-8")
        command = [sys.executable, "-m", "vulture", "--config", str(config),
                   "--min-confidence", str(min_confidence)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == _REPORT_IS_NOT_EMPTY:
        return _without_what_is_inside(callers, result.stdout)
    if result.returncode != _NOTHING_TO_REPORT:
        raise ScanDidNotRun(
            f"vulture exited {result.returncode} instead of scanning "
            f"{', '.join(str(target) for target in targets)}:\n{result.stdout}{result.stderr}"
        )
    return ""


def _vulture_config_reading(*paths: Path | str) -> str:
    """A JSON string is a TOML basic string, so each path is spelled by `json.dumps`."""
    listed = ", ".join(json.dumps(Path(path).as_posix(), ensure_ascii=False) for path in paths)
    return f"[tool.vulture]\npaths = [{listed}]\n"


_FINDING = re.compile(r"^(?P<path>.+?):\d+: ")


def _without_what_is_inside(callers: tuple[Path, ...], report: str) -> str:
    files = {caller for caller in callers if not caller.is_dir()}
    directories = [caller for caller in callers if caller.is_dir()]

    def inside_a_caller(line: str) -> bool:
        finding = _FINDING.match(line)
        if finding is None:
            return False
        path = (Path.cwd() / finding["path"]).resolve()
        return path in files or any(directory in path.parents for directory in directories)

    return "".join(line for line in report.splitlines(keepends=True) if not inside_a_caller(line))


def tracked_python(checkout: Path | str) -> list[Path]:
    listed = subprocess.run(["git", "-C", str(checkout), "ls-files", "-z", "--", "*.py"],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    files = [Path(checkout) / name for name in listed.stdout.split("\0") if name]
    if not files:
        raise ScanDidNotRun(f"nothing to read: {checkout} tracks no Python\n{listed.stderr}")
    return files


def _reports(targets, whitelist, min_confidence, each_alone, callers) -> str:
    """vulture matches names across everything it is handed, so packages scanned together hide each other's dead code."""
    callers = tuple(callers)
    if not each_alone:
        return scan(*targets, whitelist=whitelist, min_confidence=min_confidence, callers=callers)
    return "".join(scan(target, whitelist=whitelist, min_confidence=min_confidence, callers=callers)
                   for target in targets)


def assert_no_dead_code(
    *targets: Path | str,
    whitelist: Path | str | None = None,
    min_confidence: int = 60,
    each_alone: bool = False,
    callers: Iterable[Path | str] = (),
) -> None:
    report = _reports(targets, whitelist, min_confidence, each_alone, callers)
    assert not report, (
        "vulture found dead code. Delete it, or -- if the caller is a framework "
        "vulture cannot see -- add the name to the whitelist with a comment "
        f"saying who calls it:\n{report}"
    )


# `vulture --make-whitelist` spells an attribute `_.name`; `_` is a placeholder, not a name.
_WHITELIST_PLACEHOLDER = "_"


def _names_the_whitelist_suppresses(whitelist: Path | str) -> set[str]:
    """vulture counts any mention in the whitelist file: `_.name` for an attribute, a bare name otherwise."""
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
    callers: Iterable[Path | str] = (),
) -> None:
    _refuse_a_whitelist_inside_the_scan(targets, whitelist)
    report = _reports(targets, None, min_confidence, each_alone, callers)
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
    return {
        path.name for path in Path(root).iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
        and not path.name.startswith((".", "_"))
    }


def assert_every_package_is_scanned(root, scanned, *, ignoring=("tests",)) -> None:
    unnamed = sorted(packages_under(root) - set(scanned) - set(ignoring))
    assert not unnamed, (
        "packages beside the scanned ones that no gate names: "
        + ", ".join(unnamed) + ". Name them in the scan, or in `ignoring` with a reason."
    )


DEAD_CODE_LINT_RULES = ("F401", "F811", "F841")

UNREAD_ARGUMENT_RULES = ("ARG001",)


def assert_nothing_is_imported_or_assigned_and_left_unread(root, *targets) -> None:
    found = lint.findings_for_rules(root, DEAD_CODE_LINT_RULES, *targets)
    assert not found, "ruff found dead code:\n" + "\n".join(found)


_UNREAD_ARGUMENT = re.compile(r"^(?P<path>.+?):\d+:\d+: [A-Z]+\d+ .*`(?P<name>[^`]+)`$")


def _allowed_by(finding: str) -> str:
    found = _UNREAD_ARGUMENT.match(finding)
    return f"{Path(found['path']).as_posix()}: {found['name']}" if found else finding


def assert_no_function_takes_an_argument_it_never_reads(
    root, *targets, rules=UNREAD_ARGUMENT_RULES, allowing=(),
) -> None:
    found = lint.findings_for_rules(root, rules, *targets)
    found = unread.not_allowed({finding: _allowed_by(finding) for finding in found}, allowing)
    assert not found, "ruff found unread arguments:\n" + "\n".join(found)
