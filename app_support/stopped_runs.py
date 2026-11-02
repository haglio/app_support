"""On Windows, Git Bash can break the chain of parents that stopping a job follows; the run then goes on, and every console
program it starts dies at start-up with 0xC0000142."""
from __future__ import annotations

import os
import sys
import time

from app_support import processes
from app_support.threading_utils import start_daemon_thread

_STOPPED = ("this run's console closed at {at}: the job running it was stopped or the shell that "
            "started it ended, and a console program it starts from now on dies at start-up with "
            "exit code 3221225794 (0xC0000142), so the run stops here")


def pytest_sessionstart(session) -> None:
    console = processes.console_host_of(os.getpid()) if sys.platform == "win32" else None
    if console:
        start_daemon_thread(target=_stop_once_it_closes, args=(session, console), name="stopped_runs")


def _stop_once_it_closes(session, console: int) -> None:
    if processes.wait_for_end(console):
        session.shouldstop = _STOPPED.format(at=time.strftime("%H:%M:%S"))
