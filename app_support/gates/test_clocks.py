from __future__ import annotations

import pytest

from app_support.clocks import jobs_without_a_clock, per_test_clock_s
from app_support.dependencies import declared_dependencies
from app_support.gates import Checkout

pytestmark = pytest.mark.repo_check


def test_every_test_runs_under_its_own_clock(pytestconfig):
    declared_not_merely_in_effect = pytestconfig.getini("addopts")

    assert per_test_clock_s(declared_not_merely_in_effect), f"no per-test --timeout among {declared_not_merely_in_effect}"
    assert "--timeout-method=thread" in declared_not_merely_in_effect


def test_every_workflow_job_runs_under_its_own_clock(pytestconfig):
    workflows = Checkout.of(pytestconfig).root / ".github" / "workflows"
    unclocked = {path.name: jobs_without_a_clock(path.read_text(encoding="utf-8"))
                 for path in sorted(workflows.glob("*.y*ml"))}

    assert unclocked, f"no workflows found in {workflows}"
    assert {name: jobs for name, jobs in unclocked.items() if jobs} == {}, (
        "a hang before pytest arms its own clock, in collection, a plugin or pip, is caught by nothing but the job's")


def test_the_plugin_that_keeps_the_clock_is_declared_where_ci_installs_it(pytestconfig):
    """pytest rejects an unknown option before collecting, so a missing pytest-timeout is a usage error, not a red test;
    the shared development venv has the plugin whether the repo declares it or not."""
    assert "pytest-timeout" in declared_dependencies(Checkout.of(pytestconfig).pyproject)
