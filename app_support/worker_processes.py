from __future__ import annotations

import ctypes
import io
import subprocess
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

import pytest

TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE = 2

_THIS_PROCESS = wintypes.HANDLE(-1)


def _give_way_to_what_he_is_using() -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetPriorityClass(_THIS_PROCESS, subprocess.BELOW_NORMAL_PRIORITY_CLASS)


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


def pytest_configure(config) -> None:
    if hasattr(config, "workerinput"):
        if sys.platform == "win32":
            _give_way_to_what_he_is_using()
        return
    chosen = config.option
    if getattr(chosen, "numprocesses", None) and chosen.maxfail and chosen.maxschedchunk is None:
        chosen.maxschedchunk = TESTS_DEALT_AT_A_TIME_WHEN_STOPPING_AT_A_FAILURE
