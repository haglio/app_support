"""The family's coverage settings and floor, published once instead of measured nowhere.

A repo adopts both in a few lines::

    # pyproject.toml
    addopts = "... -p app_support.coverage_gate --cov --cov-report="

    # tests/test_coverage.py
    from app_support.coverage_gate import assert_config_is_the_familys

    ROOT = Path(__file__).resolve().parent.parent
    SHIPPED = ("scripture",)

    def test_the_coverage_config_is_the_familys():
        assert_config_is_the_familys(ROOT / ".coveragerc", SHIPPED)

and commits the `.coveragerc` that `render_config` writes: the family's settings, the
packages the repo ships, whatever it says it does not unit-test with the reason it
gives, and its floor -- the number measured the day it adopted this, which the run
refuses to go below. The floor is raised as coverage climbs and never lowered, so the
config test refuses a file that drifted anywhere but there.

The measuring rides the unit suite rather than a second pass over the tree: pytest-cov
collects while the suite runs and this plugin decides whether the floor applies, which
it does only to a run of the whole suite -- a narrowed run measures a fraction of the
code and would fail every time. pytest-cov is a dev dependency of the repo asking for
the gate, never a dependency of this package.
"""
from __future__ import annotations

import configparser
import difflib
from pathlib import Path
from typing import NamedTuple

import pytest


class NotUnitTested(NamedTuple):
    """A file a repo says it does not unit-test, and the reason it gives."""

    path: str
    because: str


_EXCLUDED_LINES = ("if TYPE_CHECKING:", 'if __name__ == "__main__":')

_STOOD_DOWN = pytest.StashKey[str]()

# Read with `getattr`, not off a settled namespace: the last four are the cache
# plugin's options and every repo here runs `-p no:cacheprovider`, so they are not
# options at all and asking the run for them would raise.
_NARROWINGS = (
    ("keyword", "-k {}"),
    ("markexpr", "-m {}"),
    ("deselect", "--deselect"),
    ("maxfail", "--maxfail={}"),
    ("no_cov", "--no-cov"),
    ("lf", "--lf"),
    ("failedfirst", "--ff"),
    ("newfirst", "--nf"),
    ("stepwise", "--sw"),
)


def render_config(shipped, not_unit_tested=(), floor=0.0) -> str:
    """The `.coveragerc` a repo commits: the family's settings, the packages it
    ships, what it does not unit-test with the reason, and its floor."""
    omitted = "".join(f"    # {shell.because}\n    {shell.path}\n" for shell in not_unit_tested)
    return (
        "[run]\n"
        "source =\n"
        + "".join(f"    {name}\n" for name in shipped)
        + ("omit =\n" + omitted if omitted else "")
        + "relative_files = true\n"
        "\n"
        "[report]\n"
        "precision = 2\n"
        f"fail_under = {floor}\n"
        "exclude_also =\n"
        + "".join(f"    {line}\n" for line in _EXCLUDED_LINES)
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
    why = why_this_is_not_the_whole_suite(config)
    if why is not None:
        # pytest-cov reads the floor off the namespace it was handed before the
        # conftests loaded, which is not the one `config.option` ends up being.
        config.pluginmanager.get_plugin("_cov").options.cov_fail_under = None
        config.stash[_STOOD_DOWN] = why


def pytest_terminal_summary(terminalreporter) -> None:
    why = terminalreporter.config.stash.get(_STOOD_DOWN, None)
    if why is not None:
        terminalreporter.write_line(f"coverage floor not checked: {why}")


def floor_of(coveragerc) -> float:
    """The number a repo's own `.coveragerc` says its coverage may not go below."""
    parsed = configparser.ConfigParser()
    parsed.read_string(Path(coveragerc).read_text(encoding="utf-8"))
    return parsed.getfloat("report", "fail_under")


def assert_config_is_the_familys(coveragerc, shipped, not_unit_tested=()) -> None:
    """*coveragerc* is `render_config` of its own floor, byte for byte, and every
    path it names is still in the repo."""
    coveragerc = Path(coveragerc)
    written = coveragerc.read_text(encoding="utf-8")
    expected = render_config(shipped, not_unit_tested, floor_of(coveragerc))
    if written != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), written.splitlines(keepends=True),
            "the family's", str(coveragerc)))
        raise AssertionError(
            f"{coveragerc} is not the family's coverage config plus this repo's floor:\n{diff}")
    repo = coveragerc.parent
    for name in shipped:
        if not (repo / name).is_dir():
            raise AssertionError(f"{coveragerc} measures {name}, which is not a directory in {repo}")
    for shell in not_unit_tested:
        if not (repo / shell.path).exists():
            raise AssertionError(f"{coveragerc} excuses {shell.path}, which {repo} no longer has")
