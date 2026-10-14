"""Shared fixtures — and the process every test here borrows a piece of.

This package's whole job is the process-wide scaffolding eight apps install, so
its tests install it too: exception hooks, faulthandler's stream, a rotating file
handler on a named logger. None of that belongs to the next test, and pytest's
own reporting is the first casualty when it is left standing.
"""
from __future__ import annotations

import contextlib
import ctypes
import faulthandler
import logging
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

import app_support
from app_support.siblings import assert_imported_from_checkout

_DELETE = 0x00010000
_SHARED_WITH_EVERYONE = 0x1 | 0x2 | 0x4
_OPEN_EXISTING = 3


def pytest_configure(config):
    """Refuse a run that is testing a different checkout than the one it is in.

    This repo's directory is named for the package inside it, and every consumer
    installs the package editable from the primary checkout -- so from a
    worktree, ``python -m pytest`` resolves ``app_support`` to the primary and
    the suite goes green about code the branch never touched.  It is silent:
    only a module the primary does not have at all fails, and an edit to one it
    does have passes while never being run.  ``PYTHONPATH=<this checkout>``
    is the fix, and the message says so.
    """
    assert_imported_from_checkout(app_support, checkout=config.rootpath)


class Branch:
    """A git repository checked out on ``branch``, which forks from ``main``."""

    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.path), *args], check=True, capture_output=True)

    def commit(self, files: dict[str, str], message: str = "a change") -> None:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)


@pytest.fixture
def branch_from(tmp_path):
    """Make a repository whose ``main`` holds *files*, on a branch just made from it."""
    def make(files: dict[str, str]) -> Branch:
        branch = Branch(tmp_path / "repo")
        branch.path.mkdir()
        branch.git("init", "-q", "-b", "main")
        branch.git("config", "user.email", "someone@example.com")
        branch.git("config", "user.name", "Someone")
        branch.commit(files, "the base")
        branch.git("checkout", "-q", "-b", "branch")
        return branch
    return make


@contextlib.contextmanager
def _held_open(path: Path, *, access: int, share: int, disposition: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                     ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    normal = 0x80
    handle = kernel32.CreateFileW(str(path), access, share, None, disposition, normal, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    still_open = [handle]

    def let_go() -> None:
        while still_open:
            kernel32.CloseHandle(still_open.pop())

    try:
        yield let_go
    finally:
        let_go()


@pytest.fixture
def held_open():
    return _held_open


@pytest.fixture
def child_on_its_own_desktop():
    """A sleeping child on a desktop made for the test, as ``(desktop name, pid)``."""
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)), ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
        ]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    user32.CreateDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL,
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(StartupInfo),
        ctypes.POINTER(ProcessInformation)]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_all, create_no_window = 0x10000000, 0x08000000

    desktop = "AppSupportTest" + uuid.uuid4().hex
    handle = user32.CreateDesktopW(desktop, None, None, 0, generic_all, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    startup = StartupInfo(cb=ctypes.sizeof(StartupInfo), lpDesktop=desktop)
    started = ProcessInformation()
    command = ctypes.create_unicode_buffer(
        subprocess.list2cmdline([sys._base_executable, "-c", "import time; time.sleep(120)"]))
    try:
        if not kernel32.CreateProcessW(None, command, None, None, False, create_no_window, None, None,
                                       ctypes.byref(startup), ctypes.byref(started)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield desktop, started.dwProcessId
        finally:
            kernel32.TerminateProcess(started.hProcess, 1)
            kernel32.WaitForSingleObject(started.hProcess, 5000)
            kernel32.CloseHandle(started.hThread)
            kernel32.CloseHandle(started.hProcess)
    finally:
        user32.CloseDesktop(handle)


@pytest.fixture
def being_replaced():
    @contextlib.contextmanager
    def replacing(path: Path):
        with (
            _held_open(path, access=_DELETE, share=_SHARED_WITH_EVERYONE,
                       disposition=_OPEN_EXISTING) as the_replace_finishes,
            patch("app_support.file_channel.time.sleep",
                  side_effect=lambda _: the_replace_finishes()),
        ):
            yield
    return replacing


@pytest.fixture(autouse=True)
def _the_process_is_given_back():
    """Put back the process-wide things a test installed.

    * Both exception hooks, so a thread that dies later reaches pytest's
      reporting rather than a log file in a `tmp_path` already deleted.
    * faulthandler, so a native crash after a test that called
      ``enable_faulthandler`` still prints a traceback — the tests used to
      switch it off in their own teardown, which switched pytest's off too.
    * Every handler on a logger the test brought into being: an open
      ``RotatingFileHandler`` holds its file, and thirteen of them were being
      carried to the end of the run.
    """
    hooks = (sys.excepthook, threading.excepthook)
    faulthandler_was_on = faulthandler.is_enabled()
    loggers_before = set(logging.Logger.manager.loggerDict)

    yield

    sys.excepthook, threading.excepthook = hooks
    for name in set(logging.Logger.manager.loggerDict) - loggers_before:
        logger = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(logger, logging.Logger):
            continue  # a placeholder for a child logger; it holds nothing
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    # Unconditionally, not only when it was switched off: a test that called
    # enable_faulthandler leaves it on and pointed at a file it is about to
    # close, which is worse than off. There is no way to read back the stream it
    # had, so it goes back to the one a crash should reach.
    if faulthandler_was_on:
        faulthandler.enable(sys.__stderr__, all_threads=True)
    else:
        faulthandler.disable()
