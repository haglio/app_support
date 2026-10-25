"""Where a test that starts real programs starts them: out of his sight."""
from __future__ import annotations

import ctypes
import subprocess
import uuid


class DesktopOfItsOwn:
    """A desktop made for one test, which nothing started on it can reach his screen from."""

    _SUSPENDED, _NO_WINDOW, _UNICODE_ENVIRONMENT = 0x4, 0x08000000, 0x400
    _EXTENDED_STYLE, _TOPMOST = -20, 0x8

    def __init__(self):
        from ctypes import wintypes

        class StartupInfo(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(wintypes.BYTE)), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
            ]

        class ProcessInformation(ctypes.Structure):
            _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

        self._startup_info, self._process_information = StartupInfo, ProcessInformation
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
                                                wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        self._user32.CreateDesktopW.restype = wintypes.HANDLE
        self._user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        self._kernel32.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL,
            wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(StartupInfo),
            ctypes.POINTER(ProcessInformation)]
        self._kernel32.CreateProcessW.restype = wintypes.BOOL
        self._kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.name = "AppSupportTest" + uuid.uuid4().hex
        self._handle = self._user32.CreateDesktopW(self.name, None, None, 0, 0x10000000, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._started = []

    def start(self, command: list[str], *, environment: dict[str, str] | None = None,
              suspended: bool = False) -> int:
        startup = self._startup_info(cb=ctypes.sizeof(self._startup_info), lpDesktop=self.name)
        started = self._process_information()
        flags = self._NO_WINDOW | (self._SUSPENDED if suspended else 0)
        block = None
        if environment is not None:
            flags |= self._UNICODE_ENVIRONMENT
            block = ctypes.create_unicode_buffer(
                "".join(f"{name}={value}\0" for name, value in environment.items()) + "\0")
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not self._kernel32.CreateProcessW(None, line, None, None, False, flags, block, None,
                                             ctypes.byref(startup), ctypes.byref(started)):
            raise ctypes.WinError(ctypes.get_last_error())
        self._started.append(started)
        return started.dwProcessId

    def ended_within(self, pid: int, seconds: float) -> bool:
        started = next(each for each in self._started if each.dwProcessId == pid)
        return self._kernel32.WaitForSingleObject(started.hProcess, int(seconds * 1000)) == 0

    def shows_a_window_over_every_other(self) -> bool | None:
        from ctypes import wintypes

        each_window = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, each_window, wintypes.LPARAM]
        self._user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        found = []

        def look(window, _unused):
            if self._user32.IsWindowVisible(window):
                found.append(bool(self._user32.GetWindowLongW(window, self._EXTENDED_STYLE) & self._TOPMOST))
            return True

        self._user32.EnumDesktopWindows(self._handle, each_window(look), 0)
        return found[0] if found else None

    def close(self) -> None:
        for started in self._started:
            self._kernel32.TerminateProcess(started.hProcess, 1)
            self._kernel32.WaitForSingleObject(started.hProcess, 5000)
            self._kernel32.CloseHandle(started.hThread)
            self._kernel32.CloseHandle(started.hProcess)
        self._user32.CloseDesktop(self._handle)
