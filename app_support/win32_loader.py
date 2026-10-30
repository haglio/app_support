"""Binding a Win32 DLL at import, in a process whose ctypes may have no Windows half.

Where there is none, the handle is a stand-in that takes argtypes like the real one
and raises :class:`Win32Unavailable`, naming the entry point, when anything calls it.
"""
from __future__ import annotations

import ctypes
from typing import Any

WIN32_AVAILABLE = hasattr(ctypes, "windll")


class Win32Unavailable(RuntimeError):
    pass


class _UnavailableEntryPoint:
    def __init__(self, name: str) -> None:
        self._name = name

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        raise Win32Unavailable(f"{self._name} needs a Windows ctypes; this process has none")


class _UnavailableDll:
    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, entry_point: str) -> _UnavailableEntryPoint:
        if entry_point.startswith("__"):
            raise AttributeError(entry_point)
        stand_in = _UnavailableEntryPoint(f"{self._name}.{entry_point}")
        setattr(self, entry_point, stand_in)
        return stand_in


class _UnavailableCallbackType:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise Win32Unavailable("a Win32 callback prototype needs a Windows ctypes; this process has none")


def load_dll(name: str, *, use_last_error: bool = False) -> Any:
    if not WIN32_AVAILABLE:
        return _UnavailableDll(name)
    if use_last_error:
        return ctypes.WinDLL(name, use_last_error=True)  # type: ignore[attr-defined]
    return getattr(ctypes.windll, name)  # type: ignore[attr-defined]


def win_functype(restype: Any, *argtypes: Any) -> Any:
    if not WIN32_AVAILABLE:
        return _UnavailableCallbackType
    return ctypes.WINFUNCTYPE(restype, *argtypes)  # type: ignore[attr-defined]


def get_last_error() -> int:
    if not WIN32_AVAILABLE:
        raise Win32Unavailable("ctypes.get_last_error needs a Windows ctypes; this process has none")
    return ctypes.get_last_error()  # type: ignore[attr-defined]
