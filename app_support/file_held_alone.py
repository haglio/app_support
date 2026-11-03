from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

if os.name == "nt":
    import msvcrt

_READ_AND_WRITE, _SHARED_WITH_NOBODY, _OPEN_ALWAYS, _NORMAL = 0xC0000000, 0, 4, 0x80


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


def held_alone(path: Path) -> int:
    handle = _kernel32().CreateFileW(str(path), _READ_AND_WRITE, _SHARED_WITH_NOBODY, None, _OPEN_ALWAYS,
                                     _NORMAL, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def let_go_of(handle: int) -> None:
    _kernel32().CloseHandle(handle)


def opened_alone(path: str, flags: int) -> int:
    return msvcrt.open_osfhandle(held_alone(Path(path)), flags & os.O_APPEND)
