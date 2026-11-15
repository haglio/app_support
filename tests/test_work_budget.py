from __future__ import annotations

import os
import subprocess
import sys

from app_support.work_budget import OUT_OF_ITS_OWN_TIME


def _run_on_a_budget(tmp_path, budget_s: float, program: str) -> subprocess.CompletedProcess:
    (tmp_path / "the_program.py").write_text(program, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        filter(None, (str(tmp_path), os.environ.get("PYTHONPATH"))))}
    return subprocess.run(
        [sys.executable, "-m", "app_support.work_budget", str(budget_s), "the_program", "an-argument"],
        env=env, capture_output=True, text=True, timeout=60, check=False)


def test_a_program_that_waits_longer_than_its_budget_without_working_runs_to_its_end(tmp_path):
    ran = _run_on_a_budget(tmp_path, 0.5, "import sys, time\ntime.sleep(2)\nsys.exit(3)\n")

    assert ran.returncode == 3, ran.stderr


def test_a_program_that_has_done_more_of_its_own_work_than_its_budget_is_ended(tmp_path):
    ran = _run_on_a_budget(tmp_path, 0.2, "while True:\n    pass\n")

    assert ran.returncode == OUT_OF_ITS_OWN_TIME, ran.stderr


def test_the_program_is_handed_its_own_arguments(tmp_path):
    ran = _run_on_a_budget(tmp_path, 30, "import sys\nprint(sys.argv[1:])\n")

    assert ran.stdout.strip() == "['an-argument']", ran.stderr
