from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Callable

import pytest
from eventually import eventually

from app_support import processes
from app_support.threading_utils import start_daemon_thread

LIFESPAN_S = 300
TO_START_S = 120.0
PROMPTLY_S = 30.0


class ALauncherAndItsChild:
    def __init__(self) -> None:
        self._mark = "APP_SUPPORT_TEST_" + uuid.uuid4().hex
        self.command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "ping", "-n", str(LIFESPAN_S), "127.0.0.1"]
        self.env = {self._mark: "1"}

    def left_running(self) -> list[processes.Process]:
        return self._marked("cmd.exe", "ping.exe")

    def has_started_its_child(self) -> bool:
        return bool(self._marked("ping.exe"))

    def _marked(self, *names: str) -> list[processes.Process]:
        return [process for process in processes.running() if process.name.lower() in names
                and self._mark in processes.environment_names(process.pid)]


def timed_once(started: Callable[[], bool]) -> type[subprocess.Popen]:
    class ItsTimeStartsOnceItHasStarted(subprocess.Popen):
        def communicate(self, input=None, timeout=None):
            if not eventually(started, within_s=TO_START_S):
                raise AssertionError(f"the child had not started {TO_START_S:g} s after it was asked to")
            return super().communicate(input, timeout)

    return ItsTimeStartsOnceItHasStarted


def within(seconds: float, step: Callable[[], object]) -> object:
    outcome: list[object] = []

    def take() -> None:
        try:
            outcome.append(step())
        except Exception as raised:
            outcome.append(raised)

    start_daemon_thread(target=take).join(seconds)
    if not outcome:
        pytest.fail(f"still waiting {seconds:g} s after it started")
    return outcome[0]
