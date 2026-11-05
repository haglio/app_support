from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE = 2

_THIS_PROCESS = wintypes.HANDLE(-1)


def _give_way_to_what_he_is_using() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetPriorityClass(_THIS_PROCESS, subprocess.BELOW_NORMAL_PRIORITY_CLASS)


def pytest_configure(config) -> None:
    if hasattr(config, "workerinput"):
        if sys.platform == "win32":
            _give_way_to_what_he_is_using()
        return
    chosen = config.option
    if getattr(chosen, "numprocesses", None) and chosen.maxfail and chosen.maxschedchunk is None:
        chosen.maxschedchunk = TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE
