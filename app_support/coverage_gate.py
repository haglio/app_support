"""The family's coverage settings and floor, published once instead of measured nowhere.

A repo adopts both in a line::

    # pyproject.toml
    addopts = "... -p app_support.gates.pytest_plugin -p app_support.coverage_gate --cov --cov-report="

and commits the `.coveragerc` that `render_config` writes: the family's settings,
whatever the repo says it does not unit-test with the reason it gives, and its floor,
the number the run refuses to go below. The floor is the one line the config test lets
differ from repo to repo, and it rises with the suite: a whole run that beats it by a
point fails and names the number to raise it to, half a point under what the run
reached. What a repo does not unit-test is named
there and nowhere else, so the config test also counts the lines of what is measured
that carry `pragma: no cover`, and refuses more than the repo says it still carries --
none, unless its pyproject's [tool.haglio.coverage] says `max-pragmas`.

What is measured is the repo itself, less its tests: `source = .` reaches the root's
own modules and every package under it, which a list of package names does not -- a
root module is neither a package nor a directory, and coverage drops one silently,
which is how a repo's entry point stops being part of its own number. Coverage skips
dot-directories as it walks, so the agents' worktrees under `.claude`, the venv, the
caches and the temporary roots a suite writes are all passed over without being named.

The measuring rides the unit suite rather than a second pass over the tree: pytest-cov
collects while the suite runs and this plugin decides whether the floor applies, which
it does only to a run of the whole suite -- a narrowed run measures a fraction of the
code and would fail every time. pytest-cov is a dev dependency of the repo asking for
the gate, never a dependency of this package.
"""
from __future__ import annotations

import configparser
import contextlib
import difflib
import fnmatch
import json
import os
import re
import tempfile
from pathlib import Path
from typing import NamedTuple

import pytest
from coverage.config import DEFAULT_EXCLUDE

from app_support.gates import Checkout, over


class NotUnitTested(NamedTuple):
    """A file a repo says it does not unit-test, and the reason it gives."""

    path: str
    because: str


UNCOVERED = "uncovered_lines"
_EXCLUDED_LINES = ("if TYPE_CHECKING:", 'if __name__ == "__main__":')

_STOOD_DOWN = pytest.StashKey[str]()

# Read with `getattr`, not off a settled namespace: the last four are the cache
# plugin's options and every repo here runs `-p no:cacheprovider`, so they are not
# options at all and asking the run for them would raise.
_NARROWINGS = (
    ("keyword", "-k {}"),
    ("markexpr", "-m {}"),
    ("deselect", "--deselect"),
    ("no_cov", "--no-cov"),
    ("lf", "--lf"),
    ("failedfirst", "--ff"),
    ("newfirst", "--nf"),
    ("stepwise", "--sw"),
)


_NOT_WHAT_A_REPO_SHIPS = (
    NotUnitTested("tests/*", "the repo's own tests"),
    NotUnitTested("vulture_whitelist.py", "names that quiet the dead-code scan, not code that runs"),
)


def render_config(not_unit_tested=(), floor=0.0) -> str:
    """The `.coveragerc` a repo commits: the family's settings, what this repo does
    not unit-test with the reason, and its floor."""
    omitted = "".join(f"    # {shell.because}\n    {shell.path}\n"
                      for shell in (*_NOT_WHAT_A_REPO_SHIPS, *not_unit_tested))
    excluded = "".join(f"    {line}\n" for line in _EXCLUDED_LINES)
    return (
        "[run]\n"
        "source =\n"
        "    .\n"
        "omit =\n"
        f"{omitted}"
        "relative_files = true\n"
        "\n"
        "[report]\n"
        "precision = 2\n"
        f"fail_under = {floor}\n"
        "exclude_also =\n"
        f"{excluded}"
    )


def why_this_is_not_the_whole_suite(config) -> str | None:
    """Why the floor does not apply to this run, or None when it does.

    A floor is a statement about the whole suite. Held against a run somebody
    narrowed -- one test while debugging, the changed tests the flake gate repeats,
    a `-k` -- it compares a fraction of the code against the number the whole suite
    reaches, so it would fail every time and the answer would mean nothing.
    """
    chosen = config.option
    if chosen.file_or_dir:
        return "the run named " + ", ".join(chosen.file_or_dir)
    for option, said in _NARROWINGS:
        asked = getattr(chosen, option, None)
        if asked:
            return said.format(asked)
    return None


def pytest_configure(config) -> None:
    if config.pluginmanager.get_plugin("_cov") is None:
        raise pytest.UsageError(
            "this repo asks for the family's coverage floor but no coverage is being "
            "collected: its pytest addopts needs `--cov --cov-report=` beside "
            "`-p app_support.coverage_gate`")


def pytest_collection_modifyitems(config, items) -> None:
    # pytest-cov reads its settings off the namespace it was handed before the
    # conftests loaded, which is not the one `config.option` ends up being.
    measuring = config.pluginmanager.get_plugin("_cov").options
    why = why_this_is_not_the_whole_suite(config)
    if why is not None:
        measuring.cov_fail_under = None
        config.stash[_STOOD_DOWN] = why
    elif config.option.maxfail:
        measuring.no_cov_on_fail = True


def uncovered_in_report(covering, root: Path) -> dict[str, int]:
    with tempfile.TemporaryDirectory() as folder, contextlib.chdir(root):
        report = Path(folder) / "coverage.json"
        covering.json_report(outfile=str(report))
        files = json.loads(report.read_text(encoding="utf-8"))["files"]
    measured = {Path(name).as_posix(): file["summary"]["missing_lines"] for name, file in files.items()}
    return {key: lines for key, lines in measured.items() if lines}


def uncovered_rises(root: Path, covering) -> list[str]:
    entries = (Checkout(root).sections or {}).get(UNCOVERED)
    if entries is None:
        return []
    return [f"{key} leaves {held} {UNCOVERED}, over its entry of {entry}: test them, or take them out"
            for key, (held, entry) in over(entries, uncovered_in_report(covering, root)).items()]


def risen_floor(total: float, floor: float) -> float | None:
    hundredths = round(total * 100)
    if hundredths < round((floor + 1) * 100):
        return None
    return (hundredths - 50) // 10 / 10


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtestloop(session):
    finished = yield
    measuring = session.config.pluginmanager.get_plugin("_cov")
    total, floor = measuring.cov_total, measuring.options.cov_fail_under
    if session.config.option.collectonly or session.testsfailed or not floor or total is None:
        return finished
    risen = risen_floor(total, floor)
    if risen is not None:
        session.config.pluginmanager.get_plugin("terminalreporter").write(
            f"\nERROR: coverage of {total:.2f}% beats the floor of {floor}% by a point or more: "
            f"raise fail_under in .coveragerc to {risen}, so what the suite has reached is kept\n",
            red=True, bold=True)
        session.testsfailed += 1
    for rise in uncovered_rises(session.config.rootpath, measuring.cov_controller.cov):
        session.config.pluginmanager.get_plugin("terminalreporter").write(f"\nERROR: {rise}\n", red=True, bold=True)
        session.testsfailed += 1
    return finished


def pytest_terminal_summary(terminalreporter) -> None:
    why = terminalreporter.config.stash.get(_STOOD_DOWN, None)
    if why is not None:
        terminalreporter.write_line(f"coverage floor not checked: {why}")


def floor_of(coveragerc) -> float:
    """The number a repo's own `.coveragerc` says its coverage may not go below."""
    parsed = configparser.ConfigParser()
    parsed.read_string(Path(coveragerc).read_text(encoding="utf-8"))
    return parsed.getfloat("report", "fail_under")


def assert_config_is_the_familys(coveragerc, not_unit_tested=(), max_pragmas=0) -> None:
    """*coveragerc* is `render_config` of its own floor, byte for byte, every file it
    excuses is still in the repo, and no more lines of what it measures carry
    `pragma: no cover` than *max_pragmas*."""
    coveragerc = Path(coveragerc)
    written = coveragerc.read_text(encoding="utf-8")
    expected = render_config(not_unit_tested, floor_of(coveragerc))
    if written != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), written.splitlines(keepends=True),
            "the family's", str(coveragerc)))
        raise AssertionError(
            f"{coveragerc} is not the family's coverage config plus this repo's floor:\n{diff}")
    repo = coveragerc.parent
    for shell in not_unit_tested:
        if not (repo / shell.path).exists():
            raise AssertionError(f"{coveragerc} excuses {shell.path}, which {repo} no longer has")
    excused = _lines_excused_where_they_stand(repo, (*_NOT_WHAT_A_REPO_SHIPS, *not_unit_tested))
    if len(excused) > max_pragmas:
        raise AssertionError(
            f"{len(excused)} lines of {repo} carry `pragma: no cover`, over its ceiling of "
            f"{max_pragmas}. Name what the repo does not unit-test in its pyproject's "
            "[tool.haglio.coverage] not-unit-tested, a file of its own with the reason, rather than excusing lines where they stand; "
            "the ceiling only comes down:\n" + "\n".join(excused))


def _lines_excused_where_they_stand(repo: Path, unmeasured) -> list[str]:
    pragma = re.compile(DEFAULT_EXCLUDE[0])
    return [f"{source}:{number}"
            for source in _python_files_coverage_walks(repo)
            if not any(fnmatch.fnmatch(source, shell.path) for shell in unmeasured)
            for number, line in enumerate((repo / source).read_text(encoding="utf-8").splitlines(), 1)
            if pragma.search(line)]


def _python_files_coverage_walks(repo: Path) -> list[str]:
    found = []
    for folder, folders, files in os.walk(repo):
        folders[:] = sorted(name for name in folders if not name.startswith("."))
        found += [Path(folder, name).relative_to(repo).as_posix()
                  for name in sorted(files) if name.endswith(".py")]
    return found
