"""Programs Git Bash starts from one of its own, which Windows sees with no parent and almost
no environment once the runtime's handover is done."""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app_support import processes


def git_bash() -> Path:
    git = shutil.which("git")
    for folder in Path(git).resolve().parents if git else ():
        if (bash := folder / "usr" / "bin" / "bash.exe").is_file():
            return bash
    raise AssertionError("no Git Bash beside the git on PATH")


def waited_for(fits: Callable[[processes.Process], object], what: str) -> processes.Process:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if found := [process for process in processes.running() if fits(process)]:
            return found[0]
        time.sleep(0.05)
    raise AssertionError(f"{what} never showed among the running processes")


class GitBashPrograms:
    """Each start is Git Bash's shell, started from here, starting a second program of its own
    that carries a mark only it has, and *naming* beside it, and is handed back once it says it
    is running, before which the runtime has not yet set up its environment."""

    def __init__(self) -> None:
        self._shells: list[subprocess.Popen] = []
        self._programs: list[processes.Process] = []

    def start(self, env: dict[str, str], *, naming: str = "") -> tuple[subprocess.Popen, processes.Process]:
        mark = "git-bash-program-" + uuid.uuid4().hex
        shell = subprocess.Popen([str(git_bash()), "-c",
                                  f"/usr/bin/bash -c 'echo running; read -t 120' {mark}-$0 \"$1\"; true", "it", naming],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        self._shells.append(shell)
        shell.stdout.readline()
        self._programs.append(waited_for(lambda process: f"{mark}-it" in process.cmdline, mark))
        return shell, self._programs[-1]

    def close(self) -> None:
        for shell in self._shells:
            shell.stdin.close()
            shell.stdout.close()
            shell.kill()
            shell.wait()
        for program in self._programs:
            _ended(program)


def _ended(program: processes.Process) -> None:
    deadline = time.monotonic() + 10
    while (program.pid, program.started) in {(p.pid, p.started) for p in processes.running()}:
        if time.monotonic() > deadline:
            with contextlib.suppress(OSError):
                os.kill(program.pid, signal.SIGTERM)
            raise AssertionError(f"{program.cmdline} went on after its input closed")
        time.sleep(0.05)
