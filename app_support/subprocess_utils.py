"""Spawning child processes: hidden, and ended whole when their time runs out or their parent ends.

Every app here shells out to something console-based — ffprobe, PowerShell, a
launcher script — from a process that is itself windowed. On Windows a child
console process pops a black window on the user's screen for as long as it runs,
which for a per-clip ffprobe means flickering during playback. Suppressing it
takes two independent settings, and both are needed: ``CREATE_NO_WINDOW`` stops
the console being allocated, and ``STARTUPINFO.wShowWindow = SW_HIDE`` covers the
child that asks for a window anyway.
"""
from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from app_support import win32

logger = logging.getLogger(__name__)


def hidden_subprocess_kwargs(*, creationflags: int = 0) -> dict[str, Any]:
    """``Popen``/``check_output`` keyword arguments that keep a child invisible.

    Empty off Windows, where there is no console to suppress — so a caller can
    splat this unconditionally.  *creationflags* are OR-ed onto the hiding one,
    for a child that also needs to be detached, or run at a lower priority:
    a caller that added those by hand got the console flag and forgot the
    ``STARTUPINFO`` half every time.

    For a console child.  A child that opens windows of its own -- another app
    of the family -- must not be started with this: Windows shows such a
    child's first window the way ``STARTUPINFO`` says to, which is hidden.
    """
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW | creationflags,
            "startupinfo": startupinfo}


def run_process_tree(arguments: Sequence[str], *, timeout: float | None,
                     **popen_kwargs) -> subprocess.CompletedProcess:
    child = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kwargs)
    with ending_together(child) as end_all:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except BaseException:
            end_all()
            child.wait()
            raise
    return subprocess.CompletedProcess(arguments, child.returncode, stdout, stderr)


def tie_to_this_process(child: subprocess.Popen) -> None:
    try:
        win32.a_job_ending_with_this_process(int(child._handle))
    except OSError as refused:
        logger.warning("pid %s is not tied to this process, so it can outlive it: %s", child.pid, refused)


@contextlib.contextmanager
def ending_together(child: subprocess.Popen) -> Iterator[Callable[[], None]]:
    try:
        job = win32.JobObject(int(child._handle)) if sys.platform == "win32" else None
    except OSError:
        job = None
    if job is None:
        yield child.kill
    else:
        with job:
            yield job.end_all
