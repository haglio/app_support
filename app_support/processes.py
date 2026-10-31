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
# Windows' undocumented query for the console host serving a process; the answer's two low bits are flags.
_CONSOLE_HOST_INFORMATION = 49
_CONSOLE_HOST_FLAGS = 3
_INFO_LENGTH_MISMATCH = 0xC0000004
_UNIX_EPOCH_AS_FILETIME = 116444736000000000
_STILL_ACTIVE = 259
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0
# The x64 layouts psutil reads through as well: PEB.ProcessParameters, and in
# RTL_USER_PROCESS_PARAMETERS the StandardOutput and StandardError handles, the
# Environment pointer, DesktopInfo (a UNICODE_STRING: length, maximum, padding, pointer)
# and EnvironmentSize.
_PEB_PROCESS_PARAMETERS = 0x20
_PARAMETERS_ENVIRONMENT = 0x80
_PARAMETERS_DESKTOP_INFO = 0xC0
_PARAMETERS_ENVIRONMENT_SIZE = 0x3F0
_PARAMETERS_OUTPUT_AND_ERRORS = (0x28, 0x30)
_LARGEST_READ = 1 << 20
_DUP_HANDLE = 0x0040
_DUPLICATE_SAME_ACCESS = 0x2
_FILE_TYPE_DISK = 1
_LONGEST_PATH = 32768
# Git Bash runs its programs on a POSIX runtime, which hands a program it starts the
# environment through the runtime's exported `environ` and gives Windows only the few
# names a process needs to start.
_POSIX_RUNTIMES = frozenset({"msys-2.0.dll", "cygwin1.dll"})
_LIST_ALL_MODULES = 0x3
_MOST_MODULES = 1024
_MOST_NAMES = 4096
_NAME_READ = 256
_PAGE = 0x1000
# A PE image: where its PE header is, and from that header the optional header, whose
# magic marks a PE32+ image and whose first data directory is the exports.
_PE_HEADER_AT = 0x3C
_OPTIONAL_HEADER_AT = 24
_PE32_PLUS = 0x20B
_EXPORTS_AT = _OPTIONAL_HEADER_AT + 112


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
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                         ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD]
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel32.K32EnumProcessModulesEx.restype = wintypes.BOOL
    kernel32.K32EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel32.K32GetModuleBaseNameW.restype = wintypes.DWORD
    kernel32.K32GetModuleBaseNameW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
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
    return [process for pid, ppid, name in entries if (process := _described(pid, ppid, name))]


def _described(pid: int, ppid: int, name: str) -> Process | None:
    """The process, or None for one that has ended and is listed only while
    something still holds a handle to it."""
    handle = _kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid) if pid else None
    if not handle:
        return Process(pid, ppid, 0.0, name, "", "")
    try:
        if _has_ended(handle):
            return None
        return Process(pid, ppid, _started(handle), name, _exe(handle), _command_line(handle))
    finally:
        _kernel32.CloseHandle(handle)


def _has_ended(handle) -> bool:
    code = wintypes.DWORD()
    return bool(_kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value != _STILL_ACTIVE


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


def children(process: Process, among: Mapping[int, Process]) -> list[Process]:
    return [child for child in among.values() if child.ppid == process.pid and child.started >= process.started]


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
    return _number(_read(handle, address, 8))


def _number(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _parameters(handle) -> int:
    basics = _BasicInformation()
    if _ntdll.NtQueryInformationProcess(handle, _BASIC_INFORMATION, ctypes.byref(basics),
                                        ctypes.sizeof(basics), None):
        raise OSError("the process's basic information could not be read")
    return _pointer(handle, basics.PebBaseAddress + _PEB_PROCESS_PARAMETERS)


def _from_its_memory(pid: int, read, *, access: int = 0):
    handle = _kernel32.OpenProcess(_QUERY_INFORMATION | _VM_READ | access, False, pid)
    if not handle:
        return None
    try:
        return read(handle, _parameters(handle))
    except (OSError, TypeError, ValueError):
        return None
    finally:
        _kernel32.CloseHandle(handle)


def wait_for_end(pid: int) -> bool:
    handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, _INFINITE) == _WAIT_OBJECT_0
    finally:
        _kernel32.CloseHandle(handle)


def console_host_of(pid: int) -> int | None:
    handle = _kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        host = ctypes.c_size_t()
        if _ntdll.NtQueryInformationProcess(handle, _CONSOLE_HOST_INFORMATION, ctypes.byref(host),
                                            ctypes.sizeof(host), None):
            return None
        return (host.value & ~_CONSOLE_HOST_FLAGS) or None
    finally:
        _kernel32.CloseHandle(handle)


def desktop_of(pid: int) -> str | None:
    def read(handle, parameters: int) -> str:
        desktop_info = _read(handle, parameters + _PARAMETERS_DESKTOP_INFO, 16)
        length = _number(desktop_info[0:2])
        text_at = _number(desktop_info[8:16])
        return _read(handle, text_at, length).decode("utf-16-le", "replace") if length and text_at else ""

    return _from_its_memory(pid, read)


def output_files(pid: int) -> frozenset[str]:
    def read(handle, parameters: int) -> frozenset[str]:
        handed = (_pointer(handle, parameters + offset) for offset in _PARAMETERS_OUTPUT_AND_ERRORS)
        return frozenset(path for value in handed if (path := _file_behind(handle, value)))

    return _from_its_memory(pid, read, access=_DUP_HANDLE) or frozenset()


def _file_behind(owner, value: int) -> str:
    copy = wintypes.HANDLE()
    if not value or not _kernel32.DuplicateHandle(owner, value, _kernel32.GetCurrentProcess(), ctypes.byref(copy),
                                                  0, False, _DUPLICATE_SAME_ACCESS):
        return ""
    try:
        if _kernel32.GetFileType(copy) != _FILE_TYPE_DISK:
            return ""
        path = ctypes.create_unicode_buffer(_LONGEST_PATH)
        length = _kernel32.GetFinalPathNameByHandleW(copy, path, len(path), 0)
        return path.value.removeprefix("\\\\?\\") if 0 < length < len(path) else ""
    finally:
        _kernel32.CloseHandle(copy)


def environment_names(pid: int) -> frozenset[str]:
    def read(handle, parameters: int) -> frozenset[str]:
        block_at = _pointer(handle, parameters + _PARAMETERS_ENVIRONMENT)
        size = min(_pointer(handle, parameters + _PARAMETERS_ENVIRONMENT_SIZE), _LARGEST_READ)
        text = _read(handle, block_at, size).decode("utf-16-le", "replace")
        windows = frozenset(entry.partition("=")[0] for entry in text.split("\0") if entry and entry[0] != "=")
        return windows | _posix_environment_names(handle)

    return _from_its_memory(pid, read) or frozenset()


def _posix_environment_names(handle) -> frozenset[str]:
    try:
        runtime = _posix_runtime(handle)
        environ = runtime and _exported(handle, runtime, b"environ")
        return frozenset(_names_listed_at(handle, _pointer(handle, environ))) if environ else frozenset()
    except (OSError, ValueError):
        return frozenset()


def _posix_runtime(handle) -> int | None:
    modules = (ctypes.c_void_p * _MOST_MODULES)()
    needed = wintypes.DWORD()
    if not _kernel32.K32EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed),
                                             _LIST_ALL_MODULES):
        return None
    name = ctypes.create_unicode_buffer(260)
    for module in modules[:needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        named = module and _kernel32.K32GetModuleBaseNameW(handle, module, name, len(name))
        if named and name.value.lower() in _POSIX_RUNTIMES:
            return module
    return None


def _exported(handle, base: int, wanted: bytes) -> int | None:
    header = base + _number(_read(handle, base + _PE_HEADER_AT, 4))
    if _number(_read(handle, header + _OPTIONAL_HEADER_AT, 2)) != _PE32_PLUS:
        return None
    directory = _read(handle, header + _EXPORTS_AT, 8)
    at = _number(directory[:4])
    exports = _read(handle, base + at, min(_number(directory[4:]), _LARGEST_READ))

    def field(rva: int, size: int = 4) -> int:
        return _number(exports[rva - at:rva - at + size])

    names, functions, name_list, ordinals = field(at + 24), field(at + 28), field(at + 32), field(at + 36)
    for index in range(names):
        name = field(name_list + 4 * index) - at
        if exports[name:exports.index(b"\0", name)] == wanted:
            return base + field(functions + 4 * field(ordinals + 2 * index, 2))
    return None


def _names_listed_at(handle, entries: int) -> list[str]:
    found = []
    while entries and len(found) < _MOST_NAMES and (entry := _pointer(handle, entries + 8 * len(found))):
        found.append(_name_at(handle, entry))
    return found


def _name_at(handle, address: int) -> str:
    found = b""
    while len(found) < _LARGEST_READ:
        chunk = _read(handle, address, min(_NAME_READ, _PAGE - address % _PAGE))
        name = chunk.split(b"\0", 1)[0].split(b"=", 1)[0]
        if len(name) < len(chunk):
            return (found + name).decode("utf-8", "replace")
        found += chunk
        address += len(chunk)
    return found.decode("utf-8", "replace")


def _is_claude_code(exe: str) -> bool:
    return "\\claude-code\\" in exe.lower().replace("/", "\\")


def whose(desktop: str | None, *, environment: Iterable[str] = (), ancestor_exes: Iterable[str] = (),
          child_environments: Iterable[Iterable[str]] = ()) -> str:
    if desktop and not desktop.lower().endswith("default"):
        return OFFSCREEN
    if (SESSION_MARK in set(environment) or any(_is_claude_code(exe) for exe in ancestor_exes)
            or any(SESSION_MARK in set(child) for child in child_environments)):
        return AGENT
    return HIS


def whose_process(process: Process, among: Mapping[int, Process]) -> str:
    return whose(desktop_of(process.pid), environment=environment_names(process.pid),
                 ancestor_exes=[parent.exe for parent in ancestors(process, among)],
                 child_environments=[environment_names(child.pid) for child in children(process, among)])
