"""A stalled test has to die and name itself, not hold the merge queue for six hours.

A required check with no budget stalls until GitHub's own six-hour job limit and
prints nothing that says which test stopped -- so every repo in the family puts a
clock on each test and on each workflow job, and ``test_clocks`` goes red in its
suite when one is missing rather than letting the gap pass quietly. A repo asks
for those checks by naming ``app_support.clocks.pytest_plugin`` once.

Both clocks are ceilings, not targets: a repo's per-test budget clears its
slowest test several times over, and its job budget is about three times a green
run. They bite on a hang and on nothing else.
"""
from __future__ import annotations

import re

_PER_TEST = re.compile(r"--timeout=([0-9]+)")
_JOB = re.compile(r'  "?([A-Za-z0-9_-]+)"?:\s*(#.*)?')
_CLOCK = re.compile(r'    "?timeout-minutes"?:\s*"?[1-9][0-9]*"?\s*(#.*)?')
# A job that calls one of the family's workflows is clocked by it: the clock is that
# workflow's to declare, and a caller may not declare one of its own.
_THE_FAMILYS_GATE = re.compile(r'    "?uses"?:\s*"?haglio/\.github/\.github/workflows/[a-z-]+\.yml@\S+"?\s*(#.*)?')


def per_test_clock_s(addopts: list[str]) -> int | None:
    budgets = [int(found[1]) for option in addopts if (found := _PER_TEST.fullmatch(option))]
    return budgets[-1] if budgets and budgets[-1] > 0 else None


def jobs_without_a_clock(workflow: str) -> list[str]:
    """The jobs in one workflow that do not declare ``timeout-minutes``.

    A scan rather than a YAML parse: PyYAML is not a dependency here, and adding
    one to read a single key would cost more than the key is worth. Comments are
    skipped wherever they sit, including at column 0 -- a full-line separator
    between two jobs is legal YAML, and reading it as the end of the block would
    wave through every job below it without ever looking.
    """
    unclocked: list[str] = []
    current: str | None = None
    in_jobs = False
    for line in workflow.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if not line.startswith(" "):
            break
        named = _JOB.fullmatch(line)
        if named:
            current = named.group(1)
            unclocked.append(current)
        elif current in unclocked and (_CLOCK.fullmatch(line) or _THE_FAMILYS_GATE.fullmatch(line)):
            unclocked.remove(current)
    return unclocked
