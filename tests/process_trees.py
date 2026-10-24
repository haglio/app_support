from __future__ import annotations

import os
import uuid
from collections.abc import Callable

import pytest

from app_support import processes
from app_support.threading_utils import start_daemon_thread


class ALauncherAndItsChild:
    def __init__(self) -> None:
        self._mark = "APP_SUPPORT_TEST_" + uuid.uuid4().hex
        self.command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "ping", "-n", "30", "127.0.0.1"]
        self.env = {self._mark: "1"}

    def left_running(self) -> list[processes.Process]:
        return [process for process in processes.running() if process.name.lower() in ("cmd.exe", "ping.exe")
                and self._mark in processes.environment_names(process.pid)]


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
