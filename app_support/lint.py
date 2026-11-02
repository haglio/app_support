from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

RUFF_VERSION = "0.16.6"

FAMILY_IGNORES = ("E501", "BLE001", "S110")

READ_BY_OTHER_GATES = ("ARG", "N", "S")

_SELECT = ("F", "E", "W", "I", "UP", "B", "C4", "SIM", "RUF", "PL", "PT", "DTZ", "PIE",
           "PERF", "FLY", "ISC", "RET", "FURB", "EXE")

_PER_FILE_IGNORES = {
    "**/vulture_whitelist.py": ("B018", "F821"),
    "**/tests/**": ("PLR2004",),
    "**/test_*.py": ("PLR2004",),
}

_A_FINDING = re.compile(r"^.+?:\d+:\d+: ([A-Z]+\d+) ")

_COUNTED_RULE = re.compile(r'^    "([A-Z]+\d+)",  # (\d+)$', re.MULTILINE)


def _quoted(codes) -> str:
    return ", ".join(f'"{code}"' for code in codes)


def _counted(ratchet) -> str:
    if not ratchet:
        return ""
    return (",\n    # This repo's ratchet: each rule the family config still finds here, "
            "and its places today.\n"
            + "".join(f'    "{rule}",  # {places}\n' for rule, places in ratchet.items()))


def _listed(ratchet) -> str:
    if not ratchet:
        return ""
    return (",\n    # This repo's ratchet: what the family config found here, "
            "to be worked off rule by rule.\n    " + _quoted(ratchet))


def _per_file_ignores() -> str:
    return "\n[lint.per-file-ignores]\n" + "".join(
        f'"{files}" = [{_quoted(rules)}]\n' for files, rules in _PER_FILE_IGNORES.items())


def render_config(ratchet=()) -> str:
    if isinstance(ratchet, Mapping):
        ratcheted, exempted = _counted(ratchet), _per_file_ignores()
    else:
        ratcheted, exempted = _listed(ratchet), ""
    return (
        "line-length = 100\n"
        'target-version = "py312"\n'
        "\n"
        "[lint]\n"
        f"select = [{_quoted(_SELECT)}]\n"
        f"ignore = [{_quoted(FAMILY_IGNORES)}{ratcheted}]\n"
        f"external = [{_quoted((*READ_BY_OTHER_GATES, *FAMILY_IGNORES, *ratchet))}]\n"
        f"{exempted}"
        "\n"
        "[format]\n"
        'quote-style = "double"\n'
    )


def ratchet_of(ruff_toml):
    text = Path(ruff_toml).read_text(encoding="utf-8")
    config = tomllib.loads(text).get("lint", {})
    codes = tuple(code for code in config.get("ignore", []) if code not in FAMILY_IGNORES)
    if "per-file-ignores" in config:
        places = dict(_COUNTED_RULE.findall(text))
        return {code: int(places[code]) for code in codes}
    return codes


def assert_config_is_the_familys(ruff_toml) -> None:
    written = Path(ruff_toml).read_text(encoding="utf-8")
    expected = render_config(ratchet_of(ruff_toml))
    if written != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), written.splitlines(keepends=True),
            "the family's", str(ruff_toml)))
        raise AssertionError(
            f"{ruff_toml} is not the family's ruff config plus this repo's ratchet:\n{diff}")


class LintDidNotRun(RuntimeError):
    pass


def _ruff(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ruff", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", check=False)


def ruff_version(root) -> str:
    ran = _ruff(root, "--version")
    if ran.returncode != 0:
        raise LintDidNotRun(f"ruff is not installed for {sys.executable}:\n{ran.stderr}")
    return ran.stdout.split()[-1]


def scan_targets(root, trees) -> list[str]:
    return [str(tree) for tree in trees] + [path.name for path in sorted(Path(root).glob("*.py"))]


def files_seen(root, targets) -> list[Path]:
    ran = _ruff(root, "check", "--show-files", *targets)
    if ran.returncode != 0:
        raise LintDidNotRun(f"ruff could not list {root}:\n{ran.stdout}{ran.stderr}")
    return [Path(line) for line in ran.stdout.splitlines() if line.strip()]


def _check(root, *args) -> list[str]:
    version = ruff_version(root)
    if version != RUFF_VERSION:
        raise LintDidNotRun(f"ruff {version} is not the family's {RUFF_VERSION}; pin it in [dev]")
    ran = _ruff(root, "check", "--no-fix", "--output-format", "concise", *args)
    if ran.returncode not in (0, 1):
        raise LintDidNotRun(f"ruff exited {ran.returncode} instead of scanning {root}:\n"
                            f"{ran.stdout}{ran.stderr}")
    return [line for line in ran.stdout.splitlines() if _A_FINDING.match(line)]


def findings_for_rules(root, rules, *targets) -> list[str]:
    return _check(root, "--isolated", "--select", ",".join(rules),
                  *(str(target) for target in targets))


def _refuse_a_scan_that_skipped(root, trees, targets) -> None:
    seen = files_seen(root, targets)
    for tree in trees:
        wanted = Path(tree).resolve()
        if not any(wanted in path.resolve().parents for path in seen):
            raise LintDidNotRun(f"ruff scanned nothing under {wanted}")


def _rule_of(finding: str) -> str:
    return _A_FINDING.match(finding)[1]


def assert_lint_is_clean(root, *trees) -> None:
    targets = scan_targets(root, trees)
    _refuse_a_scan_that_skipped(root, trees, targets)
    ratchet = ratchet_of(Path(root) / "ruff.toml")
    counted = ratchet if isinstance(ratchet, Mapping) else {}
    reporting_the_ratchet = ("--extend-select", ",".join(counted)) if counted else ()
    found = _check(root, *reporting_the_ratchet, *targets)
    stray = [finding for finding in found if _rule_of(finding) not in counted]
    if stray:
        raise AssertionError(
            f"ruff found {len(stray)} thing(s) under {root}:\n" + "\n".join(stray))
    moved = [_how_the_count_moved(rule, count, [f for f in found if _rule_of(f) == rule])
             for rule, count in counted.items()]
    if any(moved):
        raise AssertionError(
            f"ruff.toml's ratchet does not hold under {root}:\n" + "".join(moved))


def _how_the_count_moved(rule, count, places) -> str:
    if len(places) > count:
        return (f"{rule} has {len(places)} places, more than the {count} ruff.toml counts; "
                "every place of it:\n" + "".join(f"  {place}\n" for place in places))
    if not places:
        return f"{rule} has no places left: take it off ruff.toml's ratchet\n"
    if len(places) < count:
        return (f"{rule} has {len(places)} places, fewer than the {count} ruff.toml counts: "
                f"write {len(places)} beside it there\n")
    return ""
