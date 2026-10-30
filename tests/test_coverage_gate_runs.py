"""Which runs the coverage floor is enforced against, and that it can actually fail.

The rule cases below decide each shape of argument without a subprocess in the way;
the end-to-end cases run a real pytest against a throwaway package, because a floor
that never fails and a repo whose coverage is fine look exactly alike from here.
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from consumer_runs import run_pytest_in

from app_support import coverage_gate

MEASURING = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.coverage_gate --cov --cov-report="
testpaths = ["tests"]
"""

NOT_MEASURING = """\
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider -p app_support.coverage_gate"
testpaths = ["tests"]
"""

SHIPPED = """\
def told(what):
    return f"told {what}"


def never_called():
    return "unreached"
"""

A_TEST = """\
from pkg.mod import told


def test_it_tells():
    assert told("you") == "told you"
"""

A_FAILING_TEST = """\
def test_it_fails():
    assert False
"""


def _config(**narrowed) -> Namespace:
    settled = {"file_or_dir": [], "keyword": "", "markexpr": "", "deselect": None, "maxfail": 0}
    return Namespace(option=Namespace(**{**settled, **narrowed}))


class TestWhichRunsTheFloorApplies:
    def test_a_bare_run_is_the_whole_suite(self):
        assert coverage_gate.why_this_is_not_the_whole_suite(_config()) is None

    def test_naming_a_file_narrows_it(self):
        why = coverage_gate.why_this_is_not_the_whole_suite(_config(file_or_dir=["tests/test_a.py"]))
        assert "tests/test_a.py" in why

    def test_naming_a_directory_narrows_it_too(self):
        """Even one holding every test: a repo with two testpaths would measure one
        of them and call the other's code uncovered."""
        assert coverage_gate.why_this_is_not_the_whole_suite(_config(file_or_dir=["tests"]))

    def test_choosing_by_name_narrows_it(self):
        assert "-k" in coverage_gate.why_this_is_not_the_whole_suite(_config(keyword="told"))

    def test_choosing_by_marker_narrows_it(self):
        assert "-m" in coverage_gate.why_this_is_not_the_whole_suite(_config(markexpr="slow"))

    def test_deselecting_narrows_it(self):
        assert coverage_gate.why_this_is_not_the_whole_suite(_config(deselect=["tests/test_a.py"]))

    def test_a_run_set_to_stop_at_its_first_failure_is_still_the_whole_suite(self):
        assert coverage_gate.why_this_is_not_the_whole_suite(_config(maxfail=1)) is None

    def test_switching_the_measuring_off_narrows_it(self):
        assert coverage_gate.why_this_is_not_the_whole_suite(_config(no_cov=True))

    def test_rerunning_the_last_failures_narrows_it(self):
        assert coverage_gate.why_this_is_not_the_whole_suite(_config(lf=True))

    def test_an_option_the_cache_plugin_brings_is_not_missed_when_it_is_off(self):
        """Every repo here runs `-p no:cacheprovider`, so `--lf` and its siblings are
        not options at all and reading them off the run would raise."""
        assert coverage_gate.why_this_is_not_the_whole_suite(_config()) is None


class TestTheFloorAgainstARealRun:
    def _repo(self, tmp_path: Path, floor: float, pyproject: str = MEASURING, *, failing: bool = False) -> Path:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "mod.py").write_text(SHIPPED, encoding="utf-8")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_mod.py").write_text(A_TEST, encoding="utf-8")
        if failing:
            (tests / "test_failing.py").write_text(A_FAILING_TEST, encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        (tmp_path / ".coveragerc").write_text(
            coverage_gate.render_config((), floor), encoding="utf-8")
        return tmp_path

    def test_a_suite_within_a_point_over_its_floor_passes_and_says_the_number(self, tmp_path):
        done = run_pytest_in(self._repo(tmp_path, 74.5))

        assert done.returncode == 0, done.stdout + done.stderr
        assert "Total coverage: 75.00%" in done.stdout

    def test_a_suite_a_point_over_its_floor_fails_and_names_the_floor_to_set(self, tmp_path):
        """A floor left under what the suite reaches lets that much coverage go
        with nothing turning red, which is how every floor in the family sat
        where it was set for a month while the suites climbed past it."""
        done = run_pytest_in(self._repo(tmp_path, 74.0))

        assert done.returncode != 0, done.stdout + done.stderr
        assert "raise fail_under in .coveragerc to 74.5" in done.stdout

    def test_a_suite_under_its_floor_fails_the_run(self, tmp_path):
        done = run_pytest_in(self._repo(tmp_path, 90.0))

        assert done.returncode != 0, done.stdout + done.stderr
        assert "Required test coverage of 90.0% not reached" in done.stdout

    def test_a_run_that_only_collects_is_not_asked_to_raise_the_floor(self, tmp_path):
        """What it measures is what importing the tests ran, and a run of
        `--collect-only` is how an agent shows which checks a run gathers."""
        done = run_pytest_in(self._repo(tmp_path, 10.0), "--collect-only")

        assert done.returncode == 0, done.stdout + done.stderr
        assert "raise fail_under" not in done.stdout

    def test_a_run_told_to_hold_no_floor_is_not_asked_to_raise_one(self, tmp_path):
        """Each part of a suite run in parts is told `--cov-fail-under=0`: it
        measures only its share, and the floor is held over the parts together."""
        done = run_pytest_in(self._repo(tmp_path, 10.0), "--cov-fail-under=0", "--cov-report=term")

        assert done.returncode == 0, done.stdout + done.stderr
        assert "raise fail_under" not in done.stdout

    def test_a_run_set_to_stop_at_its_first_failure_is_held_to_the_floor_when_every_test_passes(self, tmp_path):
        done = run_pytest_in(self._repo(tmp_path, 90.0), "-x")

        assert done.returncode != 0, done.stdout + done.stderr
        assert "Required test coverage of 90.0% not reached" in done.stdout

    def test_a_run_stopped_by_a_failure_reports_the_failure_alone(self, tmp_path):
        """What was measured is whatever ran before the failure, and the run is red
        already: a coverage failure beside it would send the reader after the wrong one."""
        done = run_pytest_in(self._repo(tmp_path, 90.0, failing=True), "-x")

        assert done.returncode != 0, done.stdout + done.stderr
        assert "test_it_fails" in done.stdout
        assert "Required test coverage" not in done.stdout

    def test_a_run_with_a_failing_test_reports_the_failure_and_not_the_floor(self, tmp_path):
        done = run_pytest_in(self._repo(tmp_path, 10.0, failing=True))

        assert done.returncode != 0, done.stdout + done.stderr
        assert "test_it_fails" in done.stdout
        assert "raise fail_under" not in done.stdout

    def test_a_narrowed_run_is_not_held_to_the_floor_and_says_so(self, tmp_path):
        done = run_pytest_in(self._repo(tmp_path, 90.0), "tests/test_mod.py")

        assert done.returncode == 0, done.stdout + done.stderr
        assert "coverage floor not checked" in done.stdout

    def test_a_repo_asking_for_the_floor_without_measuring_is_refused(self, tmp_path):
        """A gate reading a number nobody collected passes forever, and a repo whose
        coverage is fine looks the same from the outside."""
        done = run_pytest_in(self._repo(tmp_path, 90.0, NOT_MEASURING))

        assert done.returncode != 0, done.stdout + done.stderr
        assert "no coverage is being collected" in done.stdout + done.stderr
