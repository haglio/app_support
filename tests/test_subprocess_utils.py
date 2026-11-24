from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from eventually import eventually
from process_trees import (
    LIFESPAN_S,
    PROMPTLY_S,
    TO_START_S,
    ALauncherAndItsChild,
    timed_once,
    within,
)

from app_support import processes, win32
from app_support.subprocess_utils import (
    hidden_subprocess_kwargs,
    run_process_tree,
    tie_to_this_process,
)

_windows_half = pytest.mark.skipif(
    not hasattr(subprocess, "STARTUPINFO"),
    reason="the Windows half of subprocess is what these check, against the real STARTUPINFO and flags, so a wrong "
           "constant fails and a moved import does not",
)
_LIMIT_S = 1.0


def _on_platform(name: str):
    return patch("app_support.subprocess_utils.sys.platform", name)


def test_off_windows_no_creation_flags_are_asked_for():
    with _on_platform("linux"):
        assert hidden_subprocess_kwargs() == {}


def test_off_windows_the_added_flag_has_nowhere_to_go_either():
    with _on_platform("linux"):
        assert hidden_subprocess_kwargs(creationflags=8) == {}


@_windows_half
def test_both_suppressions_are_applied_not_just_one():
    # Windows: CREATE_NO_WINDOW alone leaves a child that explicitly asks for a window
    # showing one, and SW_HIDE alone still allocates the console; a console
    # flashing over the video is the bug either half on its own permits.
    with _on_platform("win32"):
        result = hidden_subprocess_kwargs()

    assert set(result) == {"creationflags", "startupinfo"}
    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW
    startupinfo = result["startupinfo"]
    assert isinstance(startupinfo, subprocess.STARTUPINFO)
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE


@_windows_half
def test_a_flag_the_caller_adds_rides_with_the_hiding_one():
    with _on_platform("win32"):
        result = hidden_subprocess_kwargs(creationflags=8)

    assert result["creationflags"] == subprocess.CREATE_NO_WINDOW | 8
    assert result["startupinfo"].wShowWindow == subprocess.SW_HIDE


@_windows_half
def test_a_child_out_of_time_ends_with_everything_it_started_rather_than_waiting_on_them():
    launcher = ALauncherAndItsChild()

    ended = within(TO_START_S + _LIMIT_S + PROMPTLY_S, lambda: run_process_tree(
        launcher.command, timeout=_LIMIT_S, popen=timed_once(launcher.has_started_its_child),
        env={**os.environ, **launcher.env}, **hidden_subprocess_kwargs()))

    assert isinstance(ended, subprocess.TimeoutExpired)
    assert not launcher.left_running()


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
time.sleep(int(sys.argv[3]))
"""


@_windows_half
def test_output_still_held_open_outside_the_child_does_not_hold_up_its_end(tmp_path):
    handed_over = tmp_path / "handed over"
    holder = subprocess.Popen([sys._base_executable, "-c", f"import time; time.sleep({LIFESPAN_S})"],
                              **hidden_subprocess_kwargs())
    try:
        ended = within(TO_START_S + _LIMIT_S + PROMPTLY_S, lambda: run_process_tree(
            [sys._base_executable, "-c", _HANDS_ITS_OUTPUT_TO, str(holder.pid), str(handed_over), str(LIFESPAN_S)],
            timeout=_LIMIT_S, popen=timed_once(handed_over.exists), **hidden_subprocess_kwargs()))
    finally:
        holder.kill()
        holder.wait()

    assert handed_over.exists()
    assert isinstance(ended, subprocess.TimeoutExpired)


_TIES_ONE_THAT_STARTS_ANOTHER = """
import gc, subprocess, sys, time
from app_support.subprocess_utils import tie_to_this_process
STARTS_ONE_OF_ITS_OWN = ("import subprocess, sys, time; sys.stdin.readline(); "
                         "subprocess.Popen([sys.executable, '-c', 'import pathlib, sys, time; "
                         "pathlib.Path(sys.argv[2]).touch(); time.sleep(int(sys.argv[3]))', *sys.argv[1:]], "
                         "creationflags=subprocess.CREATE_NO_WINDOW); time.sleep(int(sys.argv[3]))")
child = subprocess.Popen([sys.executable, "-c", STARTS_ONE_OF_ITS_OWN, *sys.argv[1:]], stdin=subprocess.PIPE,
                         creationflags=subprocess.CREATE_NO_WINDOW)
tie_to_this_process(child)
gc.collect()
child.stdin.write(b"start yours\\n")
child.stdin.flush()
time.sleep(int(sys.argv[3]))
"""


@_windows_half
def test_a_child_tied_to_this_process_ends_with_what_it_started_the_moment_this_process_does(tmp_path):
    marker = "app-support-test-" + uuid.uuid4().hex
    started = tmp_path / "the one it started has started"
    tier = subprocess.Popen([sys._base_executable, "-c", _TIES_ONE_THAT_STARTS_ANOTHER, marker, str(started),
                             str(LIFESPAN_S)], creationflags=subprocess.CREATE_NO_WINDOW)

    def tied() -> list[processes.Process]:
        return [process for process in processes.running() if marker in process.cmdline and process.pid != tier.pid]

    try:
        assert eventually(started.exists, within_s=TO_START_S), "the tied child never started one of its own"
        assert len(tied()) == 2
    finally:
        tier.kill()
        tier.wait()

    assert eventually(lambda: not tied(), within_s=PROMPTLY_S)


def test_a_tied_child_comes_back_with_the_job_that_can_free_it_later(monkeypatch):
    the_job = object()
    monkeypatch.setattr(win32, "a_job_ending_with_this_process", lambda process: the_job)

    assert tie_to_this_process(SimpleNamespace(_handle=0x1F4, pid=4321)) is the_job


def test_a_child_windows_will_not_tie_is_said_to_be_free_to_outlive_this_process(monkeypatch, caplog):
    def refused(process: int) -> None:
        raise OSError("AssignProcessToJobObject failed")

    monkeypatch.setattr(win32, "a_job_ending_with_this_process", refused)

    with caplog.at_level(logging.WARNING):
        tie = tie_to_this_process(SimpleNamespace(_handle=0x1F4, pid=4321))

    assert tie is None
    assert "4321" in caplog.text
    assert "AssignProcessToJobObject failed" in caplog.text


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

    monkeypatch.setattr(win32, "JobObject", refused)

    ended = within(_LIMIT_S + PROMPTLY_S, lambda: run_process_tree(
        [sys._base_executable, "-c", f"import time; time.sleep({LIFESPAN_S})", marker], timeout=_LIMIT_S,
        **hidden_subprocess_kwargs()))

    assert isinstance(ended, subprocess.TimeoutExpired)
    assert not [process for process in processes.running() if marker in process.cmdline]


def test_off_windows_a_child_is_run_without_asking_for_a_job(monkeypatch):
    def asked(process: int) -> None:
        raise AssertionError("a job was asked for off Windows")

    monkeypatch.setattr(win32, "JobObject", asked)
    hidden = hidden_subprocess_kwargs()

    with _on_platform("linux"):
        finished = run_process_tree([sys._base_executable, "-c", "print('said')"], timeout=60, text=True, **hidden)

    assert finished.stdout == "said\n"


_PACKAGE = Path(__file__).resolve().parent.parent / "app_support"


def _timed_children_in(package: Path) -> list[str]:
    return [f"{module.name}:{node.lineno}" for module in sorted(package.rglob("*.py"))
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
            and any(keyword.arg == "timeout" for keyword in node.keywords)]


def test_every_child_the_package_gives_a_time_limit_is_run_as_a_whole_tree():
    assert _timed_children_in(_PACKAGE) == []
