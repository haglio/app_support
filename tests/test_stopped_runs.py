"""Tests for a run that stops once the console it started in has closed.

The run that matters is a real pytest with a console of its own, which closes it the
way a stopped job's closes: its console host ends and the run lives on.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from consumer_runs import run_pytest_in

from app_support import stopped_runs
from app_support.processes import console_host_of
from app_support.threading_utils import start_daemon_thread

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32's consoles")

# Every repo of the family names the blocked-word plugin, which brings this one with it.
PYPROJECT = '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider -p app_support.sanitize.pytest_plugin"\n'
CLOSING_ITS_OWN_CONSOLE = """\
import ctypes
import os
import subprocess
import sys
from pathlib import Path

from app_support.processes import console_host_of
from app_support.threading_utils import wait_until

TERMINATE_AND_SYNCHRONIZE = 0x0001 | 0x00100000


def test_the_job_running_this_is_stopped(request):
    console = console_host_of(os.getpid())
    assert console and str(console) != Path("outer_console").read_text(), "not a console of its own"
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = ctypes.c_void_p
    host = ctypes.c_void_p(kernel32.OpenProcess(TERMINATE_AND_SYNCHRONIZE, False, console))
    kernel32.TerminateProcess(host, 1)
    kernel32.WaitForSingleObject(host, 10_000)
    wait_until(lambda: request.session.shouldstop, timeout=10)


def test_a_python_child_started_after_it():
    assert subprocess.run([sys.executable, "-c", "pass"]).returncode == 0
"""


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "family" / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (repo / "tests" / "test_stopped.py").write_text(CLOSING_ITS_OWN_CONSOLE, encoding="utf-8")
    (repo / "outer_console").write_text(str(console_host_of(os.getpid())), encoding="utf-8")
    return repo


def test_the_console_host_ending_stops_the_run_saying_when():
    session = SimpleNamespace(shouldstop=False)
    host = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(60)"],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        watching = start_daemon_thread(target=stopped_runs._stop_once_it_closes, args=(session, host.pid))
        host.kill()
        watching.join(10)
    finally:
        host.kill()
        host.wait()

    assert session.shouldstop.startswith("this run's console closed at "), session.shouldstop


def test_a_console_host_the_run_cannot_watch_never_stops_it():
    session = SimpleNamespace(shouldstop=False)

    stopped_runs._stop_once_it_closes(session, console=0)

    assert not session.shouldstop


def test_a_run_whose_console_closes_stops_after_the_test_in_progress_and_says_why(tmp_path: Path):
    done = run_pytest_in(_repo(tmp_path), "-v", "tests/test_stopped.py", creationflags=subprocess.CREATE_NO_WINDOW)

    assert done.returncode == pytest.ExitCode.INTERRUPTED, done.stdout
    assert "Interrupted: this run's console closed at" in done.stdout, done.stdout
    assert "test_a_python_child_started_after_it" not in done.stdout, done.stdout
