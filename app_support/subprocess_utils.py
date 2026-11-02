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
    """Not for a child that opens windows of its own: Windows shows such a child's first window as STARTUPINFO says, which is hidden."""
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
