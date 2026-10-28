"""The clock checks whose subject is the repository under test, not this package.

Shipped, not collected: ``app_support.clocks.pytest_plugin`` hands this file to
pytest, so a repo gets them by naming the plugin once rather than by keeping a
copy of them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app_support.clocks import jobs_without_a_clock, per_test_clock_s
from app_support.dependencies import declared_dependencies

pytestmark = pytest.mark.repo_check


def _pyproject(pytestconfig) -> Path:
    assert pytestconfig.inipath, "no pyproject declares this repo's pytest options"
    return Path(pytestconfig.inipath)


def test_every_test_runs_under_its_own_clock(pytestconfig):
    """Declared, not merely in effect: a command line can override the option,
    and what this guards is that the configuration still asks for it."""
    addopts = pytestconfig.getini("addopts")

    assert per_test_clock_s(addopts), f"no per-test --timeout among {addopts}"
    assert "--timeout-method=thread" in addopts


def test_every_workflow_job_runs_under_its_own_clock(pytestconfig):
    """The other half, and not only for the gate. A run that hangs before
    pytest's timer is armed -- in collection, in a plugin, in pip -- is caught by
    nothing but the job's clock, and that is as true of a workflow nobody is
    watching as of the required check."""
    workflows = _pyproject(pytestconfig).parent / ".github" / "workflows"
    unclocked = {path.name: jobs_without_a_clock(path.read_text(encoding="utf-8"))
                 for path in sorted(workflows.glob("*.y*ml"))}

    assert unclocked, f"no workflows found in {workflows}"
    assert {name: jobs for name, jobs in unclocked.items() if jobs} == {}


def test_the_plugin_that_keeps_the_clock_is_declared_where_ci_installs_it(pytestconfig):
    """The half no run of a suite can catch by failing.

    pytest rejects an option it does not recognize before it collects anything,
    so a `--timeout` in the config with no `pytest-timeout` in the dev extra is
    not a red test -- it is a usage error, and the required check goes red with
    no suite backing it. It cannot happen locally either, because the shared
    development venv has the plugin whether the repo asks for it or not. So the
    declaration is checked here, where a run that works can still say it is
    missing.
    """
    assert "pytest-timeout" in declared_dependencies(_pyproject(pytestconfig))
