from __future__ import annotations

import ctypes
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

import pytest

from app_support import win32

TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE = 2
BLAS_THREADS_A_WORKER_RUNS = "1"


def _give_way_to_what_he_is_using() -> None:
    win32.put_this_process_at(subprocess.BELOW_NORMAL_PRIORITY_CLASS)


class _IdleShare:
    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._last = self._times()

    def _times(self) -> tuple[int, int]:
        idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
        self._kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        ticks = [(spent.dwHighDateTime << 32) | spent.dwLowDateTime for spent in (idle, kernel, user)]
        return ticks[0], ticks[1] + ticks[2]

    def __call__(self) -> float:
        then, self._last = self._last, self._times()
        return (self._last[0] - then[0]) / max(self._last[1] - then[1], 1)


class StarvedClock(threading.Thread):
    LEAST_SHARE_COUNTED = 0.125

    def __init__(self, ceiling: float, expire: Callable[[], object], *, tick: float = 0.5,
                 idle_share: Callable[[], float] | None = None) -> None:
        super().__init__(name="app_support hang ceiling", daemon=True)
        self._ceiling, self._expire, self._tick = ceiling, expire, tick
        self._idle_share = idle_share
        self._stopped = threading.Event()

    def run(self) -> None:
        idle_share = self._idle_share or _IdleShare()
        given = 0.0
        while given < self._ceiling:
            if self._stopped.wait(self._tick):
                return
            given += self._tick * max(idle_share(), self.LEAST_SHARE_COUNTED)
        self._expire()

    def stop(self) -> None:
        self._stopped.set()
        self.join()


class _Stacks(io.StringIO):
    def sep(self, mark: str, title: str) -> None:
        self.write(f"{mark * 4} {title} {mark * 4}\n")


def _report_then_end(item, settings) -> None:
    pytest_timeout = item.config.pluginmanager.getplugin("timeout")
    stacks = _Stacks()
    pytest_timeout.dump_stacks(stacks)
    item.ihook.pytest_runtest_logreport(report=pytest.TestReport(
        item.nodeid, item.location, {}, "failed",
        f"Timeout: ran past {settings.timeout:g} s\n{stacks.getvalue()}", "call", []))
    pytest_timeout.timeout_timer(item, settings)


def pytest_timeout_set_timer(item, settings):
    if settings.method != "thread" or not hasattr(item.config, "workerinput") or sys.platform != "win32":
        return None
    clock = StarvedClock(settings.timeout, lambda: _report_then_end(item, settings))
    item.cancel_timeout = clock.stop
    clock.start()
    return True


_GB = 2**30
_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x100000
_COMMIT_WATCH = pytest.StashKey["CommitWatch"]()
_PID_FOLDER = pytest.StashKey[Path]()
_WORKERS = pytest.StashKey[dict]()
_PID_FOLDER_INPUT = "app_support_worker_pid_folder"
_SECONDS_A_WORKER_IS_GIVEN_TO_END = 30
_ENDINGS = {
    1: "the code pytest-timeout ends a worker with after reporting the timeout, and the one "
       "another program's TerminateProcess or taskkill gives it",
    0xC0000005: "an access violation",
    0xC0000017: "no memory left to give it",
    0xC00000FD: "a stack overflow",
    0xC000012D: "the computer's commit limit reached",
    0xC0000374: "a corrupted heap",
    0xC0000409: "a fail-fast: the C runtime's abort ends a program this way, and with it Qt's qFatal "
                "and a C++ exception nothing caught, running out of memory among them",
}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                *((name, ctypes.c_ulonglong) for name in (
                    "physical", "physical_free", "commit_limit", "commit_free",
                    "virtual", "virtual_free", "extended_free"))]


class _MemoryCounters(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("page_faults", wintypes.DWORD),
                *((name, ctypes.c_size_t) for name in (
                    "peak_working_set", "working_set", "peak_paged_pool", "paged_pool",
                    "peak_nonpaged_pool", "nonpaged_pool", "commit", "peak_commit"))]


def commit_free_and_limit() -> tuple[int, int]:
    status = _MemoryStatus(length=ctypes.sizeof(_MemoryStatus))
    ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status))
    return status.commit_free, status.commit_limit


_STILL_RUNNING = 0x102


class WorkerProcess:
    def __init__(self, pid: int) -> None:
        self._kernel32, self._psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        self._handle = wintypes.HANDLE(self._kernel32.OpenProcess(
            _SYNCHRONIZE | _QUERY_LIMITED_INFORMATION, False, pid))

    def ending(self, *, wait: float) -> tuple[int | None, int | None] | None:
        if not self._handle:
            return None
        ended = self._kernel32.WaitForSingleObject(self._handle, int(wait * 1000)) != _STILL_RUNNING
        code = wintypes.DWORD()
        self._kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code))
        counters = _MemoryCounters(size=ctypes.sizeof(_MemoryCounters))
        read = self._psapi.GetProcessMemoryInfo(self._handle, ctypes.byref(counters), counters.size)
        return (code.value if ended else None), (counters.peak_commit if read else None)


class CommitWatch(threading.Thread):
    def __init__(self, *, read=commit_free_and_limit, tick: float = 1.0, kept: int = 120) -> None:
        super().__init__(name="app_support commit watch", daemon=True)
        self._read, self._tick = read, tick
        self._readings: deque[tuple[int, int]] = deque([read()], maxlen=kept)
        self._stopped = threading.Event()

    def run(self) -> None:
        while not self._stopped.wait(self._tick):
            self._readings.append(self._read())

    def stop(self) -> None:
        self._stopped.set()
        self.join()

    def least_free_lately(self) -> tuple[int, int]:
        return min(self._readings)


def how_it_ended(code: int | None, peak_commit: int | None, least_free: tuple[int, int]) -> str:
    if code is None:
        said = f"it had still not ended {_SECONDS_A_WORKER_IS_GIVEN_TO_END} s later"
    else:
        said = f"it ended with exit code {code if code < 256 else hex(code).upper().replace('X', 'x')}"
        if code in _ENDINGS:
            said += f", {_ENDINGS[code]}"
    if peak_commit is not None:
        said += f"; it had committed at most {peak_commit / _GB:.2f} GB"
    free, limit = least_free
    return said + (f"; the least the computer had free of its {limit / _GB:.1f} GB commit limit in the "
                   f"last two minutes was {free / _GB:.1f} GB")


def _pid_file(folder: Path, worker_id: str) -> Path:
    return folder / f"{worker_id}.pid"


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node) -> None:
    folder = node.config.stash.get(_PID_FOLDER, None)
    if folder is not None:
        node.workerinput[_PID_FOLDER_INPUT] = str(folder)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodeready(node) -> None:
    folder = node.config.stash.get(_PID_FOLDER, None)
    try:
        pid = int(_pid_file(folder, node.gateway.id).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return
    node.config.stash[_WORKERS][node.gateway.id] = WorkerProcess(pid)


@pytest.hookimpl(optionalhook=True, trylast=True)
def pytest_handlecrashitem(report) -> None:
    config = report.node.config
    worker = config.stash.get(_WORKERS, {}).get(report.node.gateway.id)
    ending = worker and worker.ending(wait=_SECONDS_A_WORKER_IS_GIVEN_TO_END)
    if ending:
        report.longrepr = f"{report.longrepr}: {how_it_ended(*ending, config.stash[_COMMIT_WATCH].least_free_lately())}"


def pytest_unconfigure(config) -> None:
    watch = config.stash.get(_COMMIT_WATCH, None)
    if watch is not None:
        watch.stop()
    folder = config.stash.get(_PID_FOLDER, None)
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def pytest_configure(config) -> None:
    if hasattr(config, "workerinput"):
        if sys.platform == "win32":
            _give_way_to_what_he_is_using()
        if _PID_FOLDER_INPUT in config.workerinput:
            _pid_file(Path(config.workerinput[_PID_FOLDER_INPUT]), config.workerinput["workerid"]).write_text(
                str(os.getpid()), encoding="utf-8")
        return
    os.environ.setdefault("OPENBLAS_NUM_THREADS", BLAS_THREADS_A_WORKER_RUNS)
    if sys.platform == "win32" and getattr(config.option, "numprocesses", None):
        config.stash[_COMMIT_WATCH] = watch = CommitWatch()
        config.stash[_PID_FOLDER] = Path(tempfile.mkdtemp(prefix="app_support-workers-"))
        config.stash[_WORKERS] = {}
        watch.start()
    deal_tests_as_chosen(config.option)


def deal_tests_as_chosen(chosen) -> None:
    if getattr(chosen, "numprocesses", None) and chosen.maxfail and chosen.maxschedchunk is None:
        chosen.maxschedchunk = TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE
