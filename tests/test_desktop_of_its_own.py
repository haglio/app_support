"""A desktop made for one test, which nothing started on it outlives."""
from __future__ import annotations

import sys

import pytest
from desktop_of_its_own import DesktopOfItsOwn
from eventually import eventually

from app_support import processes

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="a desktop of its own")
STARTS_ONE_THAT_STAYS_AND_ENDS = (
    "import subprocess, sys; subprocess.Popen([sys.executable, '-c', "
    "'import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(60)', sys.argv[1]], "
    "creationflags=subprocess.CREATE_NO_WINDOW)")


@windows_only
def test_what_a_process_left_running_on_it_is_ended_when_it_closes(tmp_path):
    left_running = tmp_path / "running"
    desktop = DesktopOfItsOwn()
    try:
        child = desktop.start([sys._base_executable, "-c", STARTS_ONE_THAT_STAYS_AND_ENDS, str(left_running)])
        assert desktop.ended_within(child, 30)
        assert eventually(left_running.exists, within_s=30)
    finally:
        desktop.close()

    assert desktop.running_on_it() == []


@windows_only
def test_a_pid_it_listed_that_now_names_a_process_elsewhere_is_left_running(
        child_on_its_own_desktop, desktop_of_its_own, monkeypatch):
    _, elsewhere = child_on_its_own_desktop
    desktop = DesktopOfItsOwn()
    listings = [[processes.Process(pid=elsewhere, ppid=0, started=0.0, name="python.exe", exe="", cmdline="")], []]
    monkeypatch.setattr(desktop, "running_on_it", lambda: listings.pop(0))

    desktop.close()

    assert not desktop_of_its_own.ended_within(elsewhere, 0)
