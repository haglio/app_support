"""The children the family starts: kept invisible, and ended whole when their time runs out.

The invisible half runs against the real ``STARTUPINFO`` and the real flag
constants, with only the platform patched, so a wrong constant fails and a
refactor of the import does not.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from unittest.mock import patch

import pytest
from process_trees import ALauncherAndItsChild, within

from app_support import processes, win32
from app_support.subprocess_utils import hidden_subprocess_kwargs, run_process_tree
from app_support.threading_utils import wait_until

_windows_half = pytest.mark.skipif(
    not hasattr(subprocess, "STARTUPINFO"),
    reason="the Windows half of subprocess is what these check",
)
_LIMIT_S = 1.0
_PROMPTLY_S = 5.0


def _platform(name: str):
    return patch("app_support.subprocess_utils.sys.platform", name)


def test_off_windows_no_creation_flags_are_asked_for():
    with _platform("linux"):
        assert hidden_subprocess_kwargs() == {}


def test_off_windows_the_added_flag_has_nowhere_to_go_either():
    with _platform("linux"):
        assert hidden_subprocess_kwargs(creationflags=8) == {}


@_windows_half
def test_both_suppressions_are_applied_not_just_one():
    # CREATE_NO_WINDOW alone leaves a child that explicitly asks for a window
    # showing one, and SW_HIDE alone still allocates the console; a console
    # flashing over the video is the bug either half on its own permits.
    with _platform("win32"):
        result = hidden_subprocess_kwargs()

    assert set(result) == {"creationflags", "startupinfo"}
    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW
    startupinfo = result["startupinfo"]
    assert isinstance(startupinfo, subprocess.STARTUPINFO)
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


@_windows_half
def test_a_flag_the_caller_adds_rides_with_the_hiding_one():
    # A child that also has to be detached, or run at a lower priority: OR-ed
    # here, so the caller never again spells the console flag by hand and
    # forgets the STARTUPINFO half.
    with _platform("win32"):
        result = hidden_subprocess_kwargs(creationflags=8)

    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW | 8
    assert result["startupinfo"].wShowWindow == subprocess.SW_HIDE


@_windows_half
def test_a_child_out_of_time_ends_with_everything_it_started_rather_than_waiting_on_them():
    launcher = ALauncherAndItsChild()

    ended = within(_LIMIT_S + _PROMPTLY_S, lambda: run_process_tree(
        launcher.command, timeout=_LIMIT_S, env={**os.environ, **launcher.env}, **hidden_subprocess_kwargs()))

    def nothing_it_started_is_left_running() -> bool:
        return not launcher.left_running()

    assert isinstance(ended, subprocess.TimeoutExpired)
    wait_until(nothing_it_started_is_left_running, timeout=_PROMPTLY_S)


_HANDS_ITS_OUTPUT_TO = """
import ctypes, pathlib, sys, time
from ctypes import wintypes
PROCESS_DUP_HANDLE, STD_OUTPUT_HANDLE, DUPLICATE_SAME_ACCESS = 0x0040, -11, 2
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.GetStdHandle.restype = ctypes.c_void_p
kernel32.GetCurrentProcess.restype = ctypes.c_void_p
kernel32.DuplicateHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
holder = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, int(sys.argv[1]))
copy = ctypes.c_void_p()
if kernel32.DuplicateHandle(kernel32.GetCurrentProcess(), kernel32.GetStdHandle(STD_OUTPUT_HANDLE), holder,
                            ctypes.byref(copy), 0, False, DUPLICATE_SAME_ACCESS):
    pathlib.Path(sys.argv[2]).touch()
time.sleep(30)
"""
_TIME_TO_START_PYTHON_S = 3.0


@_windows_half
def test_output_still_held_open_outside_the_child_does_not_hold_up_its_end(tmp_path):
    handed_over = tmp_path / "handed over"
    holder = subprocess.Popen([sys._base_executable, "-c", "import time; time.sleep(30)"],
                              **hidden_subprocess_kwargs())
    try:
        ended = within(_TIME_TO_START_PYTHON_S + _PROMPTLY_S, lambda: run_process_tree(
            [sys._base_executable, "-c", _HANDS_ITS_OUTPUT_TO, str(holder.pid), str(handed_over)],
            timeout=_TIME_TO_START_PYTHON_S, **hidden_subprocess_kwargs()))
    finally:
        holder.kill()
        holder.wait()

    assert handed_over.exists()
    assert isinstance(ended, subprocess.TimeoutExpired)


def test_what_a_child_that_finishes_in_time_printed_comes_back_with_how_it_ended():
    finished = run_process_tree(
        [sys._base_executable, "-c", "import sys; print('said'); sys.stderr.write('complained'); sys.exit(3)"],
        timeout=60, text=True, **hidden_subprocess_kwargs())

    assert (finished.stdout, finished.stderr, finished.returncode) == ("said\n", "complained", 3)


@_windows_half
def test_a_child_windows_will_not_put_in_a_job_is_still_ended_at_its_limit(monkeypatch):
    marker = "app-support-test-" + uuid.uuid4().hex

    def refused(process: int) -> None:
        raise OSError("AssignProcessToJobObject failed")

    def the_child_is_gone() -> bool:
        return not [process for process in processes.running() if marker in process.cmdline]

    monkeypatch.setattr(win32, "JobObject", refused)

    ended = within(_LIMIT_S + _PROMPTLY_S, lambda: run_process_tree(
        [sys._base_executable, "-c", "import time; time.sleep(30)", marker], timeout=_LIMIT_S,
        **hidden_subprocess_kwargs()))

    assert isinstance(ended, subprocess.TimeoutExpired)
    wait_until(the_child_is_gone, timeout=_PROMPTLY_S)


def test_off_windows_a_child_is_run_without_asking_for_a_job(monkeypatch):
    def asked(process: int) -> None:
        raise AssertionError("a job was asked for off Windows")

    monkeypatch.setattr(win32, "JobObject", asked)
    hidden = hidden_subprocess_kwargs()

    with _platform("linux"):
        finished = run_process_tree([sys._base_executable, "-c", "print('said')"], timeout=60, text=True, **hidden)

    assert finished.stdout == "said\n"

