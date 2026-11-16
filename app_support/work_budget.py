from __future__ import annotations

import os
import runpy
import sys
import threading
import time

OUT_OF_ITS_OWN_TIME = 124

_LOOKS_AGAIN_AFTER_S = 0.5


def _end_once_its_own_time_runs_out(budget_s: float) -> None:
    while time.process_time() < budget_s:
        time.sleep(_LOOKS_AGAIN_AFTER_S)
    os._exit(OUT_OF_ITS_OWN_TIME)


def run_on_a_budget(budget_s: float, module: str, *arguments: str) -> None:
    threading.Thread(target=_end_once_its_own_time_runs_out, args=(budget_s,), daemon=True).start()
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    budget, program, *its_arguments = sys.argv[1:]
    run_on_a_budget(float(budget), program, *its_arguments)
