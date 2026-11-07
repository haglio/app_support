from __future__ import annotations

import re

_PER_TEST = re.compile(r"--timeout=([0-9]+)")
_JOB = re.compile(r'  "?([A-Za-z0-9_-]+)"?:\s*(#.*)?')
_CLOCK = re.compile(r'    "?timeout-minutes"?:\s*"?[1-9][0-9]*"?\s*(#.*)?')
# GitHub Actions ends a job at six hours and names no test; a job calling a reusable workflow may not declare
# timeout-minutes of its own, so the family's gate workflow is the clock on a job that calls it.
_THE_FAMILYS_GATE = re.compile(r'    "?uses"?:\s*"?haglio/\.github/\.github/workflows/[a-z-]+\.yml@\S+"?\s*(#.*)?')


def per_test_clock_s(addopts: list[str]) -> int | None:
    budgets = [int(found[1]) for option in addopts if (found := _PER_TEST.fullmatch(option))]
    return budgets[-1] if budgets and budgets[-1] > 0 else None


def jobs_without_a_clock(workflow: str) -> list[str]:
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
