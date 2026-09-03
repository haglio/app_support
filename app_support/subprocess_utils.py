"""Spawning child processes without flashing a console window.

Every app here shells out to something console-based — ffprobe, PowerShell, a
launcher script — from a process that is itself windowed. On Windows a child
console process pops a black window on the user's screen for as long as it runs,
which for a per-clip ffprobe means flickering during playback. Suppressing it
takes two independent settings, and both are needed: ``CREATE_NO_WINDOW`` stops
the console being allocated, and ``STARTUPINFO.wShowWindow = SW_HIDE`` covers the
child that asks for a window anyway.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """``Popen``/``check_output`` keyword arguments that keep a child invisible.

    Empty off Windows, where there is no console to suppress — so a caller can
    splat this unconditionally.
    """
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}
