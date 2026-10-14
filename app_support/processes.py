"""What is running on this machine, and whose it is, read through Win32 alone.

Standard library only.
"""
from __future__ import annotations

import ctypes
import dataclasses
import os
from collections.abc import Iterable, Mapping
from ctypes import wintypes

OFFSCREEN = "offscreen"
AGENT = "agent"
HIS = "his"
# Claude Code sets it in every shell it opens and a child inherits it, so it outlives
# the parent chain Git Bash breaks whenever it runs a program through env, a pipe or a
# subshell.
SESSION_MARK = "CLAUDECODE"

_QUERY_LIMITED_INFORMATION = 0x1000
_QUERY_INFORMATION = 0x0400
_VM_READ = 0x0010
_SNAPSHOT_PROCESSES = 0x2
_COMMAND_LINE_INFORMATION = 60
_BASIC_INFORMATION = 0
_INFO_LENGTH_MISMATCH = 0xC0000004
_UNIX_EPOCH_AS_FILETIME = 116444736000000000
# The x64 layouts psutil reads through as well: PEB.ProcessParameters, and in
# RTL_USER_PROCESS_PARAMETERS the Environment pointer, DesktopInfo (a UNICODE_STRING:
# length, maximum, padding, pointer) and EnvironmentSize.
_PEB_PROCESS_PARAMETERS = 0x20
_PARAMETERS_ENVIRONMENT = 0x80
_PARAMETERS_DESKTOP_INFO = 0xC0
_PARAMETERS_ENVIRONMENT_SIZE = 0x3F0
_LONGEST_ENVIRONMENT = 1 << 20


@dataclasses.dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    started: float
    name: str
    exe: str
    cmdline: str


class _ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class _UnicodeString(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


class _BasicInformation(ctypes.Structure):
    _fields_ = [("ExitStatus", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_void_p), ("BasePriority", ctypes.c_void_p),
                ("UniqueProcessId", ctypes.c_void_p), ("InheritedFromUniqueProcessId", ctypes.c_void_p)]


def _api():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    for walk in (kernel32.Process32FirstW, kernel32.Process32NextW):
        walk.restype = wintypes.BOOL
        walk.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(ctypes.c_ulonglong)] * 4]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    return kernel32, ntdll, shell32


_kernel32, _ntdll, _shell32 = _api() if os.name == "nt" else (None, None, None)


def running() -> list[Process]:
    snapshot = _kernel32.CreateToolhelp32Snapshot(_SNAPSHOT_PROCESSES, 0)
    if snapshot in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entries = []
        entry = _ProcessEntry(dwSize=ctypes.sizeof(_ProcessEntry))
        more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            entries.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return [_described(pid, ppid, name) for pid, ppid, name in entries]


def _described(pid: int, ppid: int, name: str) -> Process:
    handle = _kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid) if pid else None
    if not handle:
        return Process(pid, ppid, 0.0, name, "", "")
    try:
        return Process(pid, ppid, _started(handle), name, _exe(handle), _command_line(handle))
    finally:
        _kernel32.CloseHandle(handle)


def _started(handle) -> float:
    created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
    if not _kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                     ctypes.byref(kernel), ctypes.byref(user)):
        return 0.0
    return (created.value - _UNIX_EPOCH_AS_FILETIME) / 10_000_000


def _exe(handle) -> str:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return ""
    return buffer.value


def _command_line(handle) -> str:
    needed = wintypes.ULONG(0)
    status = _ntdll.NtQueryInformationProcess(handle, _COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(needed))
    if status & 0xFFFFFFFF != _INFO_LENGTH_MISMATCH or not needed.value:
        return ""
    buffer = ctypes.create_string_buffer(needed.value)
    if _ntdll.NtQueryInformationProcess(handle, _COMMAND_LINE_INFORMATION, buffer, needed,
                                        ctypes.byref(needed)):
        return ""
    text = _UnicodeString.from_buffer(buffer)
    return _one_line(ctypes.wstring_at(text.Buffer, text.Length // 2)) if text.Buffer else ""


def _one_line(command_line: str) -> str:
    if not command_line.strip():
        return ""
    count = ctypes.c_int(0)
    arguments = _shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not arguments:
        return " ".join(command_line.split())
    try:
        return " ".join(" ".join(arguments[index] for index in range(count.value)).split())
    finally:
        _kernel32.LocalFree(arguments)


def ancestors(process: Process, among: Mapping[int, Process]) -> list[Process]:
    found, seen = [], {process.pid}
    child = process
    while (parent := among.get(child.ppid)) is not None and parent.pid not in seen:
        if parent.started > child.started:
            break
        found.append(parent)
        seen.add(parent.pid)
        child = parent
    return found


def this_process_and_its_parents(among: Mapping[int, Process]) -> set[int]:
    me = among.get(os.getpid())
    return {os.getpid(), os.getppid(), *(parent.pid for parent in ancestors(me, among) if me)}


def _read(handle, address: int, size: int) -> bytes:
    buffer = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not _kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(got)):
        raise OSError(ctypes.get_last_error())
    return buffer.raw[:got.value]


def _pointer(handle, address: int) -> int:
    return int.from_bytes(_read(handle, address, 8), "little")


def _parameters(handle) -> int:
    basics = _BasicInformation()
    if _ntdll.NtQueryInformationProcess(handle, _BASIC_INFORMATION, ctypes.byref(basics),
                                        ctypes.sizeof(basics), None):
        raise OSError("the process's basic information could not be read")
    return _pointer(handle, basics.PebBaseAddress + _PEB_PROCESS_PARAMETERS)


def _from_its_memory(pid: int, read):
    handle = _kernel32.OpenProcess(_QUERY_INFORMATION | _VM_READ, False, pid)
    if not handle:
        return None
    try:
        return read(handle, _parameters(handle))
    except (OSError, TypeError, ValueError):
        return None
    finally:
        _kernel32.CloseHandle(handle)


def desktop_of(pid: int) -> str | None:
    def read(handle, parameters: int) -> str:
        desktop_info = _read(handle, parameters + _PARAMETERS_DESKTOP_INFO, 16)
        length = int.from_bytes(desktop_info[0:2], "little")
        text_at = int.from_bytes(desktop_info[8:16], "little")
        return _read(handle, text_at, length).decode("utf-16-le", "replace") if length and text_at else ""

    return _from_its_memory(pid, read)


def environment_names(pid: int) -> frozenset[str]:
    def read(handle, parameters: int) -> frozenset[str]:
        block_at = _pointer(handle, parameters + _PARAMETERS_ENVIRONMENT)
        size = min(_pointer(handle, parameters + _PARAMETERS_ENVIRONMENT_SIZE), _LONGEST_ENVIRONMENT)
        text = _read(handle, block_at, size).decode("utf-16-le", "replace")
        return frozenset(entry.partition("=")[0] for entry in text.split("\0") if entry and entry[0] != "=")

    return _from_its_memory(pid, read) or frozenset()


def _is_claude_code(exe: str) -> bool:
    return "\\claude-code\\" in exe.lower().replace("/", "\\")


def whose(desktop: str | None, *, environment: Iterable[str] = (), ancestor_exes: Iterable[str] = ()) -> str:
    if desktop and not desktop.lower().endswith("default"):
        return OFFSCREEN
    if SESSION_MARK in set(environment) or any(_is_claude_code(exe) for exe in ancestor_exes):
        return AGENT
    return HIS


def whose_process(process: Process, among: Mapping[int, Process]) -> str:
    return whose(desktop_of(process.pid), environment=environment_names(process.pid),
                 ancestor_exes=[parent.exe for parent in ancestors(process, among)])
